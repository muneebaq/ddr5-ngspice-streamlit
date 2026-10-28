"""Phase 1, Lesson 3: isolated CMOS DRAM sense-amplifier testbench.

Two independent 1T1C branches simulate read-1 and read-0 simultaneously.
Each uses a complementary reference bitline and four cross-coupled MOSFETs.
Only bounded, program-generated SPICE is executed (no user netlist input).
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

import pandas as pd


DEFAULT_SENSE = {
    "cell_ff": 20,
    "bitline_ff": 300,
    "vdd": 1.10,
    "wordline_high": 1.80,
    "access_width_um": 1.0,
    "n_width_um": 4.0,
    "p_width_um": 8.0,
    "sense_enable_ns": 8.0,
}

COLUMNS = [
    "Time (s)", "Cell 1 (V)", "BL1 (V)", "REF1 (V)",
    "Cell 0 (V)", "BL0 (V)", "REF0 (V)",
    "WL (V)", "SAN (V)", "SAP (V)",
]


def ideal_charge_share(cell_ff: float, bitline_ff: float, vdd: float) -> tuple[float, float]:
    """Return theoretical BL voltages before sense-amplifier activation."""
    pre = vdd / 2
    return (
        (cell_ff * vdd + bitline_ff * pre) / (cell_ff + bitline_ff),
        (bitline_ff * pre) / (cell_ff + bitline_ff),
    )


def build_sense_netlist(**p: float) -> str:
    """Build a single safe transient netlist for positive and negative reads."""
    required = set(DEFAULT_SENSE)
    if set(p) != required:
        raise ValueError(f"Expected parameters: {', '.join(sorted(required))}")
    bounds = {
        "cell_ff": (5, 50), "bitline_ff": (100, 1000),
        "vdd": (0.9, 1.2), "wordline_high": (1.2, 2.2),
        "access_width_um": (0.5, 5), "n_width_um": (1, 12),
        "p_width_um": (2, 24), "sense_enable_ns": (6.0, 13.0),
    }
    for key, (low, high) in bounds.items():
        if not low <= float(p[key]) <= high:
            raise ValueError(f"{key} must be between {low} and {high}")

    start = p["sense_enable_ns"]
    pre = p["vdd"] / 2
    nmos = p["n_width_um"]
    pmos = p["p_width_um"]
    access = p["access_width_um"]
    branches = []
    for bit in (1, 0):
        # NMOS: D G S B; PMOS: D G S B. A true cross-coupled latch.
        branches.append(f"""* Separate read-{bit} branch
MAC{bit} cell{bit} wl bl{bit} 0 ACCESS W={access:.2f}u L=0.18u
CCELL{bit} cell{bit} 0 {p['cell_ff']:.0f}f IC={p['vdd'] if bit else 0:.5f}
CBL{bit} bl{bit} 0 {p['bitline_ff']:.0f}f IC={pre:.5f}
CREF{bit} ref{bit} 0 {p['bitline_ff']:.0f}f IC={pre:.5f}
RCELL{bit} cell{bit} 0 1e15
RBL{bit} bl{bit} 0 1e15
RREF{bit} ref{bit} 0 1e15
SPBL{bit} bl{bit} pre pre_en 0 SWPRE
SPREF{bit} ref{bit} pre pre_en 0 SWPRE
MNL{bit} bl{bit} ref{bit} san 0 NSENSE W={nmos:.2f}u L=0.18u
MNR{bit} ref{bit} bl{bit} san 0 NSENSE W={nmos:.2f}u L=0.18u
MPL{bit} bl{bit} ref{bit} sap vdd PSENSE W={pmos:.2f}u L=0.18u
MPR{bit} ref{bit} bl{bit} sap vdd PSENSE W={pmos:.2f}u L=0.18u""")

    return f"""* DDR5 Research Lab - Lesson 3: differential CMOS sense amplifier
* Teaching model only: 180 nm-style LEVEL=1 transistors, not DDR5 silicon PDK
.param VDD={p['vdd']:.5f} VPRE={pre:.5f}
.model ACCESS NMOS (LEVEL=1 VTO=0.32 KP=200u LAMBDA=0.04)
.model NSENSE NMOS (LEVEL=1 VTO=0.32 KP=200u LAMBDA=0.04)
.model PSENSE PMOS (LEVEL=1 VTO=-0.32 KP=90u LAMBDA=0.04)
.model SWPRE SW (RON=20 ROFF=1e12 VT=0.5 VH=0.1)
VSUP vdd 0 {{VDD}}
VPC pre 0 {{VPRE}}
VPREEN pre_en 0 PWL(0 1 2n 1 2.1n 0 30n 0)
VWL wl 0 PWL(0 0 4n 0 4.1n {p['wordline_high']:.4f} 25n {p['wordline_high']:.4f} 25.1n 0 30n 0)
* Both latch rails sit at VDD/2 until the sense-enable event.
VSAN san 0 PWL(0 {{VPRE}} {start:.3f}n {{VPRE}} {start + 0.1:.3f}n 0 30n 0)
VSAP sap 0 PWL(0 {{VPRE}} {start:.3f}n {{VPRE}} {start + 0.1:.3f}n {{VDD}} 30n {{VDD}})
{chr(10).join(branches)}
.ic V(cell1)={{VDD}} V(cell0)=0 V(bl1)={{VPRE}} V(ref1)={{VPRE}} V(bl0)={{VPRE}} V(ref0)={{VPRE}}
.control
set wr_singlescale
set wr_vecnames
tran 20p 30n 0 20p uic
wrdata waveform.txt v(cell1) v(bl1) v(ref1) v(cell0) v(bl0) v(ref0) v(wl) v(san) v(sap)
quit
.endc
.end
"""


def read_sense_waveform(path: Path) -> pd.DataFrame:
    first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    try:
        float(first.split()[0])
        header_rows = 0
    except (ValueError, IndexError):
        header_rows = 1
    frame = pd.read_csv(path, sep=r"\s+", header=None, skiprows=header_rows)
    frame = frame.apply(pd.to_numeric, errors="coerce").dropna()
    if frame.empty:
        raise ValueError("No numeric transient samples in waveform.txt")
    if frame.shape[1] == len(COLUMNS):
        selected = frame.copy()
    elif frame.shape[1] == 2 * (len(COLUMNS) - 1):
        selected = frame.iloc[:, [0] + list(range(1, frame.shape[1], 2))].copy()
    else:
        raise ValueError(f"Expected 10 or 18 waveform columns, got {frame.shape[1]}")
    selected.columns = COLUMNS
    selected["Time (ns)"] = selected["Time (s)"] * 1e9
    return selected


def run_sense_ngspice(netlist: str) -> tuple[pd.DataFrame | None, str, str | None]:
    binary = shutil.which("ngspice")
    if not binary:
        return None, "", "ngspice is unavailable on the cloud server. Confirm packages.txt includes ngspice and redeploy."
    with tempfile.TemporaryDirectory(prefix="sense_amp_") as dirname:
        folder = Path(dirname)
        (folder / "sense.cir").write_text(netlist, encoding="utf-8")
        try:
            completed = subprocess.run(
                [binary, "-b", "sense.cir"], cwd=folder,
                capture_output=True, text=True, timeout=35, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, "", f"ngspice launch failed: {exc}"
        logs = (completed.stdout or "") + "\n" + (completed.stderr or "")
        output = folder / "waveform.txt"
        if completed.returncode != 0 or "fatal error" in logs.lower():
            return None, logs, f"ngspice failed with exit code {completed.returncode}"
        if not output.is_file():
            return None, logs, "ngspice did not create waveform.txt"
        try:
            return read_sense_waveform(output), logs, None
        except (ValueError, OSError, pd.errors.ParserError) as exc:
            return None, logs, f"Failed to parse ngspice waveform: {exc}"


def analyze_sense_waveform(frame: pd.DataFrame, p: dict) -> dict:
    """Calculate physical, measurable verification values from ngspice samples."""
    def voltage_at(column: str, at_ns: float) -> float:
        index = (frame["Time (ns)"] - at_ns).abs().idxmin()
        return float(frame.loc[index, column])

    before_ns = 3.0  # All lines are precharged; WL has not risen.
    share_ns = min(float(p["sense_enable_ns"]) - 0.2, 7.8)
    final_ns = 20.0  # SA active and WL still high; cell should be restored.
    vdd = float(p["vdd"])
    metrics = {
        "precharge_error_mv": max(
            abs(voltage_at(column, before_ns) - vdd / 2) * 1000
            for column in ("BL1 (V)", "REF1 (V)", "BL0 (V)", "REF0 (V)")
        ),
        "read1_delta_mv": 1000 * (voltage_at("BL1 (V)", share_ns) - voltage_at("REF1 (V)", share_ns)),
        "read0_delta_mv": 1000 * (voltage_at("BL0 (V)", share_ns) - voltage_at("REF0 (V)", share_ns)),
        "bl1_final_v": voltage_at("BL1 (V)", final_ns),
        "ref1_final_v": voltage_at("REF1 (V)", final_ns),
        "bl0_final_v": voltage_at("BL0 (V)", final_ns),
        "ref0_final_v": voltage_at("REF0 (V)", final_ns),
        "cell1_final_v": voltage_at("Cell 1 (V)", final_ns),
        "cell0_final_v": voltage_at("Cell 0 (V)", final_ns),
    }
    metrics["precharge_ok"] = metrics["precharge_error_mv"] <= 5
    metrics["share_ok"] = metrics["read1_delta_mv"] >= 10 and metrics["read0_delta_mv"] <= -10
    metrics["latch_ok"] = (
        metrics["bl1_final_v"] >= .90 * vdd
        and metrics["ref1_final_v"] <= .10 * vdd
        and metrics["bl0_final_v"] <= .10 * vdd
        and metrics["ref0_final_v"] >= .90 * vdd
    )
    metrics["restore_ok"] = metrics["cell1_final_v"] >= .90 * vdd and metrics["cell0_final_v"] <= .10 * vdd
    metrics["pass"] = all(metrics[key] for key in ("precharge_ok", "share_ok", "latch_ok", "restore_ok"))
    return metrics
