"""DDR5 Research Lab: safe, parameterized 1T1C DRAM ngspice simulations.

All circuits are generated from bounded numeric controls. The app deliberately
does not execute arbitrary user-supplied SPICE scripts on the cloud server.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

import pandas as pd
import streamlit as st
from optimizer import OBJECTIVES, optimize_all


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


DEFAULTS = {
    "cell_ff": 20,
    "bitline_ff": 300,
    "supply": 1.10,
    "precharge_fraction": 0.50,
    "width_um": 1.0,
    "length_nm": 180,
    "threshold": 0.45,
    "kp_ua": 200,
    "wordline_high": 1.80,
    "driver_ron": 50,
    "time_scale": 1.0,
}

PRESETS = {
    "Baseline": DEFAULTS,
    "Small storage capacitor": {**DEFAULTS, "cell_ff": 5},
    "Heavy bitline loading": {**DEFAULTS, "bitline_ff": 1000},
    "Weak access transistor": {**DEFAULTS, "width_um": 0.5, "length_nm": 500},
    "Low wordline drive": {**DEFAULTS, "wordline_high": 1.30},
    "Slow peripheral drivers": {**DEFAULTS, "driver_ron": 500},
}


def load_preset() -> None:
    """Populate widget state before any sliders are instantiated."""
    for name, value in PRESETS[st.session_state["preset"]].items():
        st.session_state[name] = value


def restore_baseline() -> None:
    st.session_state["preset"] = "Baseline"
    load_preset()


def build_netlist(**p: float) -> str:
    """Parameterized 1T1C circuit with a Level-1 NMOS and ideal drivers."""
    supply = p["supply"]
    pre = supply * p["precharge_fraction"]
    scale = p["time_scale"]

    def stamp(points: list[tuple[float, float]]) -> str:
        """Render a PWL source with SPICE-safe continuation lines."""
        fragments = [f"{time * scale:.3f}n {voltage:.4f}" for time, voltage in points]
        rows = [" ".join(fragments[i : i + 6]) for i in range(0, len(fragments), 6)]
        return "PWL(" + "\n+ ".join(rows) + ")"

    wl = stamp([
        (0, 0), (2, 0), (2.1, p["wordline_high"]), (6, p["wordline_high"]), (6.1, 0),
        (16, 0), (16.1, p["wordline_high"]), (22, p["wordline_high"]), (22.1, 0),
        (25, 0), (25.1, p["wordline_high"]), (29, p["wordline_high"]), (29.1, 0),
        (40, 0), (40.1, p["wordline_high"]), (44, p["wordline_high"]), (44.1, 0), (50, 0),
    ])
    write1 = stamp([(0, 0), (1, 0), (1.1, 1), (6, 1), (6.1, 0), (50, 0)])
    write0 = stamp([(0, 0), (24, 0), (24.1, 1), (29, 1), (29.1, 0), (50, 0)])
    precharge = stamp([
        (0, 0), (10, 0), (10.1, 1), (14, 1), (14.1, 0),
        (34, 0), (34.1, 1), (38, 1), (38.1, 0), (50, 0),
    ])
    restore = stamp([(0, 0), (19, 0), (19.1, 1), (22, 1), (22.1, 0), (50, 0)])

    return f"""* DDR5 Research Lab - 1T1C DRAM transient testbench
* Generated numeric parameters; ngspice simulation, not a foundry PDK
.param VDD={supply:.5f}
.param VPRE={pre:.5f}
.model NACCESS NMOS (LEVEL=1 VTO={p['threshold']:.3f} KP={p['kp_ua']:.0f}u GAMMA=0.4 PHI=0.7 LAMBDA=0.05)
.model DRIVER SW (RON={p['driver_ron']:.0f} ROFF=1e12 VT=0.5 VH=0.1)
VHIGH high 0 DC {{VDD}}
VLOW low 0 DC 0
VPRE pre 0 DC {{VPRE}}
M1 cell wl bl 0 NACCESS W={p['width_um']:.2f}u L={p['length_nm']:.0f}n
CSTORAGE cell 0 {p['cell_ff']:.0f}f
CBITLINE bl 0 {p['bitline_ff']:.0f}f
RCELL cell 0 1e15
RBIT bl 0 1e15
SWRITE1 bl high cw1 0 DRIVER
SWRITE0 bl low cw0 0 DRIVER
SPRE bl pre cpre 0 DRIVER
SREST bl high crest 0 DRIVER
VWL wl 0 {wl}
VCW1 cw1 0 {write1}
VCW0 cw0 0 {write0}
VCPRE cpre 0 {precharge}
VCREST crest 0 {restore}
.ic V(cell)=0 V(bl)={{VPRE}}
.control
set wr_singlescale
set wr_vecnames
tran 20p {50 * scale:.3f}n 0 20p uic
wrdata waveform.txt v(cell) v(bl) v(wl)
meas tran write1_cell FIND v(cell) AT={8 * scale:.3f}n
meas tran read1_bl FIND v(bl) AT={18 * scale:.3f}n
meas tran restored_cell FIND v(cell) AT={23 * scale:.3f}n
meas tran write0_cell FIND v(cell) AT={31 * scale:.3f}n
meas tran read0_bl FIND v(bl) AT={42 * scale:.3f}n
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


def run_ngspice(netlist: str, timeout_seconds: int = 35) -> tuple[pd.DataFrame | None, str, str | None]:
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
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, "", f"ngspice exceeded the {timeout_seconds}-second simulation limit."
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


def apply_optimized_design() -> None:
    """Update widget state safely from a Streamlit button callback."""
    chosen = st.session_state["chosen_optimization"]["parameters"]
    for key, value in chosen.items():
        if key in DEFAULTS:
            st.session_state[key] = value
    st.session_state["preset"] = "Baseline"


def measured_margin(frame: pd.DataFrame, parameters: dict) -> float:
    """Minimum observed read-1/read-0 bitline deviation in millivolts."""
    scale = parameters["time_scale"]
    pre = parameters["supply"] * parameters["precharge_fraction"]
    read_one_index = (frame["Time (ns)"] - 18 * scale).abs().idxmin()
    read_zero_index = (frame["Time (ns)"] - 42 * scale).abs().idxmin()
    one = float(frame.loc[read_one_index, "Bitline (V)"])
    zero = float(frame.loc[read_zero_index, "Bitline (V)"])
    return 1000 * min(one - pre, pre - zero)


st.markdown('<div class="eyebrow">PHASE 1 · LESSON 2 · CLOUD NGSPICE</div>', unsafe_allow_html=True)
st.title("DDR5 Research Lab")
st.markdown("**Real ngspice circuit simulation, right from your phone.**")
st.caption("Educational 1T1C DRAM cell · Adjustable 180 nm-style Level-1 NMOS model · Not a production DDR5 PDK")

st.markdown("### Circuit parameter editor")
st.selectbox(
    "Choose an experiment preset",
    list(PRESETS),
    key="preset",
    on_change=load_preset,
)
st.button("↺ Restore baseline values", on_click=restore_baseline)

with st.expander("1. Storage and bitline", expanded=True):
    left, right = st.columns(2)
    with left:
        st.slider("Storage capacitance Ccell (fF)", 5, 50, 20, 5, key="cell_ff")
        st.slider("Supply voltage VDD (V)", 0.90, 1.20, 1.10, 0.05, key="supply")
    with right:
        st.slider("Bitline capacitance CBL (fF)", 100, 1000, 300, 50, key="bitline_ff")
        st.slider("Precharge fraction of VDD", 0.30, 0.70, 0.50, 0.05, key="precharge_fraction")

with st.expander("2. NMOS access transistor", expanded=False):
    left, right = st.columns(2)
    with left:
        st.slider("MOSFET width W (µm)", 0.5, 5.0, 1.0, 0.5, key="width_um")
        st.slider("MOSFET length L (nm)", 100, 500, 180, 10, key="length_nm")
    with right:
        st.slider("Threshold voltage VTO (V)", 0.20, 0.70, 0.45, 0.05, key="threshold")
        st.slider("Model KP (µA/V²)", 50, 500, 200, 25, key="kp_ua")

with st.expander("3. Wordline, drivers and timing", expanded=False):
    left, right = st.columns(2)
    with left:
        st.slider("Active wordline voltage (V)", 1.20, 2.20, 1.80, 0.05, key="wordline_high")
        st.slider("Driver on-resistance (Ω)", 10, 1000, 50, 10, key="driver_ron")
    with right:
        st.slider("Timing scale factor", 0.5, 3.0, 1.0, 0.25, key="time_scale")
        st.caption("Timing scale multiplies the write, precharge, read and restore event times. Voltage limits are educational and do not guarantee transistor reliability.")

st.info("Cloud safety: only this generated, bounded circuit runs on the server. External SPICE scripts cannot be uploaded for execution.")

params = {name: st.session_state[name] for name in DEFAULTS}
signature = tuple(params.values())
vpre = params["supply"] * params["precharge_fraction"]
ideal_one = (params["cell_ff"] * params["supply"] + params["bitline_ff"] * vpre) / (params["cell_ff"] + params["bitline_ff"])
ideal_zero = params["bitline_ff"] * vpre / (params["cell_ff"] + params["bitline_ff"])
m1, m2, m3, m4 = st.columns(4)
m1.metric("Precharge VBL", f"{vpre:.4f} V")
m2.metric("Ideal read-1", f"{ideal_one:.4f} V", f"+{(ideal_one-vpre)*1000:.2f} mV")
m3.metric("Ideal read-0", f"{ideal_zero:.4f} V", f"{(ideal_zero-vpre)*1000:.2f} mV")
m4.metric("Stored-1 charge", f"{params['cell_ff']*params['supply']:.2f} fC")

st.markdown("### Experiment")
st.write("Write 1 → precharge → read 1 → restore → write 0 → precharge → read 0")
netlist = build_netlist(**params)

with st.expander("View generated SPICE circuit"):
    st.code(netlist, language="text")
    st.download_button("Download .cir netlist", netlist, file_name="dram_1t1c.cir", mime="text/plain")

if st.button("▶ Run ngspice transient simulation", type="primary", use_container_width=True):
    with st.spinner("Running the circuit on the cloud server..."):
        frame, output, error = run_ngspice(netlist)
    st.session_state["simulation"] = (frame, output, error, signature)

if "simulation" in st.session_state:
    frame, output, error, last_signature = st.session_state["simulation"]
    if signature != last_signature:
        st.warning("Circuit parameters have changed. Press Run again to update the waveforms below.")
    if error:
        st.error(error)
    if frame is not None:
        st.success(f"Simulation complete — {len(frame):,} waveform samples")
        st.line_chart(
            frame.set_index("Time (ns)")[["Cell (V)", "Bitline (V)", "Wordline (V)"]],
            height=380,
        )
        a, b = st.columns(2)
        simulated_scale = last_signature[list(DEFAULTS).index("time_scale")]
        for col, label, time_ns in [(a, "Read 1", 18 * simulated_scale), (b, "Read 0", 42 * simulated_scale)]:
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
st.markdown("### Automatic circuit optimization")
st.write("Compare three search algorithms and select the strongest design for **your chosen tradeoff**. No single design maximizes speed, sensing margin, and energy efficiency simultaneously.")

with st.expander("Optimization objective and constraints", expanded=True):
    objective = st.selectbox("Optimization goal", list(OBJECTIVES))
    c1, c2, c3 = st.columns(3)
    with c1:
        min_margin_mv = st.slider("Minimum sensing margin (mV)", 5, 80, 20, 5)
    with c2:
        max_energy_fj = st.slider("Maximum energy proxy (fJ)", 50, 500, 250, 25)
    with c3:
        max_delay_ns = st.slider("Maximum RC-delay proxy (ns)", 0.1, 3.0, 1.0, 0.1)
    c4, c5 = st.columns(2)
    with c4:
        max_vdd = st.slider("Maximum supply VDD (V)", 0.90, 1.20, 1.10, 0.05)
    with c5:
        max_wordline_high = st.slider("Maximum wordline-high (V)", 1.20, 2.20, 1.80, 0.05)
    budget = st.slider("Candidate evaluations per algorithm", 24, 240, 96, 24)
    seed = st.number_input("Random seed (repeatable results)", min_value=0, max_value=100000, value=7)
    validate = st.checkbox("Validate the three finalists using ngspice", value=True)
    st.caption("Search variables: Ccell, CBL, VDD, precharge fraction, NMOS width, wordline voltage, and driver resistance. Process parameters and timing scale remain fixed at your selected values.")

limits = {
    "min_margin_mv": float(min_margin_mv),
    "max_energy_fj": float(max_energy_fj),
    "max_delay_ns": float(max_delay_ns),
    "max_vdd": float(max_vdd),
    "max_wordline_high": float(max_wordline_high),
}
opt_signature = (signature, objective, tuple(limits.values()), budget, int(seed), validate)

if st.button("⚡ Compare optimization algorithms", type="primary", use_container_width=True):
    with st.spinner("Searching the parameter space..."):
        winners = optimize_all(params, objective, limits, budget, int(seed))

    if validate:
        progress = st.progress(0, text="Checking finalists with ngspice...")
        for i, candidate in enumerate(winners):
            frame, log, error = run_ngspice(build_netlist(**candidate["parameters"]), timeout_seconds=12)
            candidate["ngspice_error"] = error
            candidate["ngspice_log"] = log
            if frame is not None:
                candidate["spice_margin_mv"] = measured_margin(frame, candidate["parameters"])
            progress.progress((i + 1) / len(winners), text=f"Checked {i + 1} of {len(winners)} finalists")
        progress.empty()

    validated = [
        item for item in winners
        if item.get("spice_margin_mv") is not None
        and item["spice_margin_mv"] >= min_margin_mv
        and item["feasible"]
    ]
    recommended = max(validated, key=lambda item: item["rank"]) if validated else winners[0]
    st.session_state["optimization_result"] = (winners, recommended, opt_signature, validate)
    st.session_state["chosen_optimization"] = recommended

if "optimization_result" in st.session_state:
    winners, recommended, prior_signature, validation_requested = st.session_state["optimization_result"]
    if opt_signature != prior_signature:
        st.warning("Optimization inputs have changed. Run the algorithms again to refresh the results.")

    st.markdown("#### Algorithm comparison")
    records = []
    for item in winners:
        m = item["metrics"]
        records.append({
            "Algorithm": item["algorithm"],
            "Constraints": "Pass" if item["feasible"] else "Not met",
            "Objective score": round(item["score"], 3),
            "Margin estimate (mV)": round(m["margin_mv"], 2),
            "Energy proxy (fJ)": round(m["energy_fj"], 1),
            "RC-delay proxy (ns)": round(m["delay_ns"], 3),
            "ngspice margin (mV)": round(item["spice_margin_mv"], 2) if "spice_margin_mv" in item else None,
        })
    st.dataframe(pd.DataFrame(records), hide_index=True, use_container_width=True)

    if not any(item["feasible"] for item in winners):
        st.warning("No search finalist met every surrogate constraint. The recommended candidate has the lowest-ranked constraint violations, not a fully feasible design. Consider relaxing the limits.")
    elif validation_requested and not any("spice_margin_mv" in item for item in winners):
        st.warning("None of the finalists could be validated by ngspice. Rankings remain surrogate-only; check the ngspice diagnostic messages below.")
    elif validation_requested and recommended.get("spice_margin_mv") is None:
        st.warning("The recommended candidate has not passed ngspice validation. It is only the best surrogate estimate.")
    elif validation_requested and recommended["spice_margin_mv"] < min_margin_mv:
        st.warning("The recommended design did not achieve the requested read margin in ngspice; it is not validated against that constraint.")
    else:
        st.success("The leading design is selected for the current objective and constraints.")

    st.markdown(f"#### Recommended candidate — {recommended['algorithm']}")
    r1, r2, r3 = st.columns(3)
    r1.metric("Estimated read margin", f"{recommended['metrics']['margin_mv']:.2f} mV")
    r2.metric("Energy proxy", f"{recommended['metrics']['energy_fj']:.1f} fJ")
    r3.metric("RC-delay proxy", f"{recommended['metrics']['delay_ns']:.3f} ns")
    st.dataframe(
        pd.DataFrame([{"Parameter": key, "Optimized value": value} for key, value in recommended["parameters"].items()]),
        hide_index=True,
        use_container_width=True,
    )
    st.button("Apply these values to the circuit controls", on_click=apply_optimized_design, use_container_width=True)
    with st.expander("ngspice validation details"):
        for item in winners:
            status = "pass" if "spice_margin_mv" in item and item["spice_margin_mv"] >= min_margin_mv else "unverified / below threshold"
            st.write(f"**{item['algorithm']}** — {status}")
            if item.get("ngspice_error"):
                st.error(item["ngspice_error"])
            if item.get("ngspice_log"):
                st.code(item["ngspice_log"][-5000:], language="text")

st.caption("Optimization uses a simplified charge-sharing, switching-energy, and RC-delay surrogate. Score units are relative, not a measured DDR5 performance metric. ngspice validates the read-margin of finalists; physical area, energy, reliability, and JEDEC compliance still require separate analysis.")

st.divider()
st.markdown("### What are we learning?")
st.write("When a charged memory cell connects to the precharged bitline, its charge is shared with the larger bitline capacitance. The tiny voltage deviation is what the sense amplifier must detect. Reading disturbs the cell, so restoration is necessary.")
st.latex(r"V_{BL} = \frac{C_{cell}V_{cell} + C_{BL}V_{pre}}{C_{cell}+C_{BL}}")
st.caption("This page models one storage cell, not a complete 32 GB module. Continue with Lesson 3 to amplify its millivolt-level read signal.")
st.page_link("pages/2_Sense_Amplifier.py", label="⚡ Open Lesson 3: CMOS sense amplifier", use_container_width=True)
