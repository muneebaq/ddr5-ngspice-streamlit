"""Phone-friendly Phase 1 / Lesson 3: transistor-level sense amplifier."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sense_amplifier import (
    DEFAULT_SENSE, analyze_sense_waveform, build_sense_netlist,
    ideal_charge_share, run_sense_ngspice,
)


st.set_page_config(page_title="Lesson 3 · CMOS Sense Amplifier", page_icon="⚡", layout="wide")
st.caption("DDR5 RESEARCH LAB · PHASE 1 · LESSON 3")
st.title("CMOS Sense Amplifier")
st.markdown(
    "A DRAM cell shares a tiny charge with its bitline. **Four cross-coupled MOSFETs** "
    "amplify this difference into a full 0 or 1 and restore the cell. "
    "This experiment simulates **read-1 and read-0 side by side**."
)
st.info("Educational 180 nm-style transistor models—not a calibrated DDR5 DRAM PDK. Your Streamlit cloud server needs ngspice installed.")

with st.expander("Lesson 3 · The operating sequence", expanded=True):
    st.markdown("""
1. **0–2 ns · Precharge:** BL and complementary /BL are charged to VDD/2.
2. **4 ns · Raise wordline:** The cell shares charge with BL; /BL is the reference.
3. **Sense enable:** The NMOS common rail SAN falls to ground, and the PMOS common rail SAP rises to VDD.
4. **20 ns · Regenerate and restore:** Positive feedback drives one bitline high, the other low, while the cell remains connected.
5. **25 ns · Lower wordline:** The restored value is isolated on the cell capacitor.

The two parallel branches differ **only in stored data**: one begins at VDD, the other at 0 V.
""")

st.subheader("1 · Set circuit parameters")
left, right = st.columns(2)
with left:
    cell_ff = st.slider("Storage capacitance (fF)", 5, 50, DEFAULT_SENSE["cell_ff"], 5)
    bitline_ff = st.slider("Bitline/reference capacitance (fF)", 100, 1000, DEFAULT_SENSE["bitline_ff"], 50)
    vdd = st.slider("Supply voltage (V)", 0.9, 1.2, DEFAULT_SENSE["vdd"], 0.05)
    wordline_high = st.slider("Active wordline voltage (V)", 1.2, 2.2, DEFAULT_SENSE["wordline_high"], 0.05)
with right:
    access_width_um = st.slider("Access NMOS width (µm)", 0.5, 5.0, DEFAULT_SENSE["access_width_um"], 0.5)
    n_width_um = st.slider("Latch NMOS width (µm)", 1.0, 12.0, DEFAULT_SENSE["n_width_um"], 1.0)
    p_width_um = st.slider("Latch PMOS width (µm)", 2.0, 24.0, DEFAULT_SENSE["p_width_um"], 2.0)
    sense_enable_ns = st.slider("Sense-enable time (ns)", 6.0, 13.0, DEFAULT_SENSE["sense_enable_ns"], 0.5)

p = dict(cell_ff=cell_ff, bitline_ff=bitline_ff, vdd=vdd, wordline_high=wordline_high,
         access_width_um=access_width_um, n_width_um=n_width_um, p_width_um=p_width_um,
         sense_enable_ns=sense_enable_ns)
signature = tuple(p.values())
ideal1, ideal0 = ideal_charge_share(cell_ff, bitline_ff, vdd)
pre = vdd / 2
margin = (ideal1 - pre) * 1000

st.subheader("2 · Predict charge sharing")
m1, m2, m3 = st.columns(3)
m1.metric("Precharge", f"{pre:.4f} V")
m2.metric("Ideal read-1 BL", f"{ideal1:.4f} V", f"+{margin:.2f} mV")
m3.metric("Ideal read-0 BL", f"{ideal0:.4f} V", f"-{margin:.2f} mV")
st.latex(r"V_{BL}=\frac{C_{cell}V_{cell}+C_{BL}(V_{DD}/2)}{C_{cell}+C_{BL}}")
st.caption("Ideal predictions before sensing. Actual waveforms appear only after ngspice runs.")

netlist = build_sense_netlist(**p)
with st.expander("View or download the transistor-level SPICE netlist"):
    st.code(netlist, language="text")
    st.download_button("Download sense_amplifier.cir", netlist, "sense_amplifier.cir", "text/plain")

st.subheader("3 · Run ngspice")
if st.button("▶ Run sense-amplifier simulation", type="primary", use_container_width=True):
    with st.spinner("Simulating both data polarities and cell restoration..."):
        frame, logs, error = run_sense_ngspice(netlist)
    st.session_state["sense_run"] = (frame, logs, error, signature, p.copy())

if "sense_run" in st.session_state:
    frame, logs, error, prior_signature, prior_params = st.session_state["sense_run"]
    if signature != prior_signature:
        st.warning("Parameters have changed. Run again to update the displayed waveforms.")
    if error:
        st.error(error)
    if frame is not None:
        readings = analyze_sense_waveform(frame, prior_params)
        st.success(f"ngspice completed — {len(frame):,} transient samples")
        st.markdown("#### Differential bitlines")
        st.line_chart(frame.set_index("Time (ns)")[["BL1 (V)", "REF1 (V)", "BL0 (V)", "REF0 (V)"]], height=340)
        st.markdown("#### Storage-cell restoration")
        st.line_chart(frame.set_index("Time (ns)")[["Cell 1 (V)", "Cell 0 (V)"]], height=250)
        with st.expander("Sense-enable rail waveforms"):
            st.line_chart(frame.set_index("Time (ns)")[["SAN (V)", "SAP (V)", "WL (V)"]], height=230)

        st.subheader("4 · Verify the experiment")
        cases = [
            ("Precharge accuracy", readings["precharge_ok"], f"max error {readings['precharge_error_mv']:.2f} mV; limit 5 mV"),
            ("Charge-sharing polarity", readings["share_ok"], f"read-1 {readings['read1_delta_mv']:+.2f} mV; read-0 {readings['read0_delta_mv']:+.2f} mV; ≥ 10 mV magnitude each"),
            ("Bitline regeneration by 20 ns", readings["latch_ok"], "BL1 and REF0 ≥ 90% VDD; BL0 and REF1 ≤ 10% VDD"),
            ("Cell restoration by 20 ns", readings["restore_ok"], "Cell1 ≥ 90% VDD; Cell0 ≤ 10% VDD"),
        ]
        results = pd.DataFrame([{"Criterion": label, "Result": "PASS" if ok else "FAIL", "Measured / threshold": detail} for label, ok, detail in cases])
        st.dataframe(results, hide_index=True, use_container_width=True)
        if readings["pass"]:
            st.success("All four teaching-bench criteria passed. Next: sensing delay and device mismatch.")
        else:
            st.warning("One or more testbench criteria failed. Try a larger cell capacitor, earlier sense enable or wider latch transistors.")
        st.download_button("⬇ Download waveform CSV", frame.to_csv(index=False),
                           "sense_amplifier_waveforms.csv", "text/csv", use_container_width=True)
    with st.expander("ngspice output and troubleshooting", expanded=bool(error)):
        st.code(logs[-12000:] if logs else "No ngspice output available.", language="text")

st.divider()
st.markdown("**Step 3 assignment:** Run the defaults, record the two charge-sharing deltas, then try Ccell = 5 fF and determine the minimum capacitance that passes all four criteria. Our next experiment will investigate mismatch and a 4×4 DRAM array.")
