"""DDR5 Research Lab: safe, parameterized 1T1C DRAM ngspice simulations.

All circuits are generated from bounded numeric controls. The app deliberately
does not execute arbitrary user-supplied SPICE scripts on the cloud server.
"""

from __future__ import annotations

import io
from pathlib import Path
import shutil
import subprocess
import tempfile

import pandas as pd
import streamlit as st


st.set_page_config(page_title="DDR5 Research Lab", page_icon="🧪", layout="wide")

st.markdown(
    """
    <style>
    .block-container {max-width: 1100px; padding-top: 2rem}
    div[data-testid="stMetric"] {background: #102a31; border: 1px solid #315d5f;
      border-radius: 12px; padding: 14px}
    .eyebrow {font-size:.75rem;letter-spacing:.18em;color:#4de0b6;font-weight:750}
    .subtle {opacity:.74;font-size:.92rem}
    </style>
    """,
    unsafe_allow_html=True,
)


def build_netlist(cell_ff: int, bitline_ff: int, supply: float, width_um: float) -> str:
    """A 180-nm educational MOS model with idealized peripheral switches."""
    pre = supply / 2
    return f"""* DDR5 Research Lab - 1T1C DRAM transient testbench
* Generated numeric parameters; ngspice simulation, not a foundry PDK
.param VDD={supply:.5f}
.param VPRE={pre:.5f}
.model NACCESS NMOS (LEVEL=1 VTO=0.45 KP=200u GAMMA=0.4 PHI=0.7 LAMBDA=0.05)
.model DRIVER SW (RON=50 ROFF=1e12 VT=0.5 VH=0.1)
VHIGH high 0 DC {{VDD}}
VLOW low 0 DC 0
VPRE pre 0 DC {{VPRE}}
M1 cell wl bl 0 NACCESS W={width_um:.2f}u L=180n
CSTORAGE cell 0 {cell_ff}f
CBITLINE bl 0 {bitline_ff}f
RCELL cell 0 1e15
RBIT bl 0 1e15
SWRITE1 bl high cw1 0 DRIVER
SWRITE0 bl low cw0 0 DRIVER
SPRE bl pre cpre 0 DRIVER
SREST bl high crest 0 DRIVER
VWL wl 0 PWL(0n 0 2n 0 2.1n 1.8 6n 1.8 6.1n 0
+ 16n 0 16.1n 1.8 22n 1.8 22.1n 0
+ 25n 0 25.1n 1.8 29n 1.8 29.1n 0
+ 40n 0 40.1n 1.8 44n 1.8 44.1n 0 50n 0)
VCW1 cw1 0 PWL(0n 0 1n 0 1.1n 1 6n 1 6.1n 0 50n 0)
VCW0 cw0 0 PWL(0n 0 24n 0 24.1n 1 29n 1 29.1n 0 50n 0)
VCPRE cpre 0 PWL(0n 0 10n 0 10.1n 1 14n 1 14.1n 0
+ 34n 0 34.1n 1 38n 1 38.1n 0 50n 0)
VCREST crest 0 PWL(0n 0 19n 0 19.1n 1 22n 1 22.1n 0 50n 0)
.ic V(cell)=0 V(bl)={{VPRE}}
.control
set wr_singlescale
set wr_vecnames
tran 20p 50n 0 20p uic
wrdata waveform.txt v(cell) v(bl) v(wl)
meas tran write1_cell FIND v(cell) AT=8n
meas tran read1_bl FIND v(bl) AT=18n
meas tran restored_cell FIND v(cell) AT=23n
meas tran write0_cell FIND v(cell) AT=31n
meas tran read0_bl FIND v(bl) AT=42n
quit
.endc
.end
"""


def read_waveform(path: Path) -> pd.DataFrame:
    """Accept ngspice wrdata's single-scale or repeated-scale columns."""
    first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    skip_header = not first.lstrip().startswith(("+", "-", ".", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
    raw = pd.read_csv(path, sep=r"\s+", header=None, skiprows=int(skip_header))
    raw = raw.apply(pd.to_numeric, errors="coerce").dropna()
    if raw.empty:
        raise ValueError("ngspice produced a waveform file without numeric samples")
    if raw.shape[1] == 4:
        selected = raw.iloc[:, [0, 1, 2, 3]].copy()
    elif raw.shape[1] == 6:
        selected = raw.iloc[:, [0, 1, 3, 5]].copy()
    else:
        raise ValueError(f"Unexpected ngspice waveform columns: {raw.shape[1]}")
    selected.columns = ["Time (s)", "Cell (V)", "Bitline (V)", "Wordline (V)"]
    selected["Time (ns)"] = selected["Time (s)"] * 1e9
    return selected


def run_ngspice(netlist: str) -> tuple[pd.DataFrame | None, str, str | None]:
    executable = shutil.which("ngspice")
    if not executable:
        return None, "", "ngspice is not installed on this server. Add 'ngspice' to packages.txt and redeploy."

    with tempfile.TemporaryDirectory(prefix="ddr5_lab_") as directory:
        folder = Path(directory)
        circuit_path = folder / "cell.cir"
        circuit_path.write_text(netlist, encoding="utf-8")
        try:
            process = subprocess.run(
                [executable, "-b", str(circuit_path)],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, "", "ngspice exceeded the 35-second simulation limit."
        except OSError as exc:
            return None, "", f"ngspice could not start: {exc}"

        logs = (process.stdout or "") + "\n" + (process.stderr or "")
        waveform_path = folder / "waveform.txt"
        if process.returncode != 0 or "fatal error" in logs.lower():
            return None, logs, f"ngspice reported an error (exit code {process.returncode})."
        if not waveform_path.exists():
            return None, logs, "ngspice finished without producing waveform.txt."
        try:
            return read_waveform(waveform_path), logs, None
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            return None, logs, f"Waveform parsing failed: {exc}"


st.markdown('<div class="eyebrow">PHASE 1 · LESSON 2 · CLOUD NGSPICE</div>', unsafe_allow_html=True)
st.title("DDR5 Research Lab")
st.markdown("**Real ngspice circuit simulation, right from your phone.**")
st.caption("Educational 1T1C DRAM cell, 180 nm NMOS model · Not a production DDR5 PDK")

with st.sidebar:
    st.header("Circuit controls")
    cell_ff = st.slider("Cell capacitance (fF)", 5, 50, 20, 5)
    bitline_ff = st.slider("Bitline capacitance (fF)", 100, 1000, 300, 50)
    supply = st.slider("VDD (V)", 0.90, 1.20, 1.10, 0.05)
    width_um = st.slider("Access NMOS width (µm)", 0.5, 5.0, 1.0, 0.5)
    st.info("Safety: only a parameterized, built-in netlist runs on the cloud server. External SPICE scripts are not executed.")

vpre = supply / 2
delta_v = (cell_ff / (cell_ff + bitline_ff)) * supply / 2
m1, m2, m3 = st.columns(3)
m1.metric("Ideal read-1 BL", f"{vpre + delta_v:.4f} V")
m2.metric("Ideal read-0 BL", f"{vpre - delta_v:.4f} V")
m3.metric("Ideal |ΔV|", f"{delta_v * 1000:.2f} mV")

st.markdown("### Experiment")
st.write("Write 1 → precharge → read 1 → restore → write 0 → precharge → read 0")
netlist = build_netlist(cell_ff, bitline_ff, supply, width_um)

with st.expander("View generated SPICE circuit"):
    st.code(netlist, language="text")
    st.download_button("Download .cir netlist", netlist, file_name="dram_1t1c.cir", mime="text/plain")

if st.button("▶ Run ngspice transient simulation", type="primary", use_container_width=True):
    with st.spinner("Running the circuit on the cloud server..."):
        frame, output, error = run_ngspice(netlist)
    st.session_state["simulation"] = (frame, output, error)

if "simulation" in st.session_state:
    frame, output, error = st.session_state["simulation"]
    if error:
        st.error(error)
    if frame is not None:
        st.success(f"Simulation complete — {len(frame):,} waveform samples")
        st.line_chart(
            frame.set_index("Time (ns)")[["Cell (V)", "Bitline (V)", "Wordline (V)"]],
            height=380,
        )
        a, b = st.columns(2)
        for col, label, time_ns in [(a, "Read 1 at 18 ns", 18), (b, "Read 0 at 42 ns", 42)]:
            index = (frame["Time (ns)"] - time_ns).abs().idxmin()
            col.metric(label, f"{frame.loc[index, 'Bitline (V)']:.4f} V")
        st.download_button(
            "⬇ Download results CSV",
            frame.to_csv(index=False),
            file_name="ddr5_ngspice_waveforms.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with st.expander("ngspice console and diagnostics", expanded=bool(error)):
        st.code(output or "No console output was received.", language="text")

st.divider()
st.markdown("### What are we learning?")
st.write("When a charged memory cell connects to the precharged bitline, its charge is shared with the larger bitline capacitance. The tiny voltage deviation is what the sense amplifier must detect. Reading disturbs the cell, so restoration is necessary.")
st.latex(r"V_{BL} = \frac{C_{cell}V_{cell} + C_{BL}V_{pre}}{C_{cell}+C_{BL}}")
st.caption("Next milestone: cross-coupled CMOS sense amplifier, then a small DRAM array. This app models one cell—not a complete 32 GB RAM module.")
