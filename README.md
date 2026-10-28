# DDR5 Research Lab — Cloud ngspice on Streamlit

A mobile-friendly Streamlit app that runs **ngspice transient simulations** of a simplified 1T1C DRAM cell and a cross-coupled CMOS sense amplifier on the cloud server. The browser acts only as a client, so an Android phone or iPhone needs no ngspice installation.

## Phase 1 · Lesson 3: CMOS sense amplifier

Open **Lesson 3 · CMOS Sense Amplifier** from the app's page navigation. This new experiment includes:

- Two independent read tests running simultaneously: a cell initially storing **1** and one storing **0**.
- A complementary bitline reference precharged to **VDD/2**, alongside each storage bitline.
- A transistor-level **four-MOSFET cross-coupled latch** for each branch, with editable NMOS width, PMOS width and sense-enable timing.
- Adjustable cell and bitline capacitance, supply voltage, access-transistor width and wordline voltage.
- Three waveform views: differential bitlines, storage cell restoration, and wordline/sense-enable rails.
- Automated checks for precharge accuracy, correct charge-sharing polarity, full-rail regeneration and read restoration.
- Downloads for both the generated `.cir` netlist and measured waveform CSV.

The baseline ideal pre-sense charge-sharing voltages for Ccell = 20 fF, CBL = 300 fF and VDD = 1.1 V are **0.584375 V** for read-1 and **0.515625 V** for read-0, against a 0.55 V reference (±34.375 mV). These are analytical values, not evidence of a completed ngspice run; actual waveforms and pass/fail decisions come from the cloud simulation.

The experimental models are educational 180 nm-style Level-1 devices rather than an official DDR5 design kit. Passing the tests does not establish yield, retention, timing compliance, or manufacturability.

## Adjustable variables

The phone-friendly parameter editor includes grouped controls for:

| Group | Parameters |
| --- | --- |
| Storage and bitline | Cell capacitance, bitline capacitance, supply voltage, precharge voltage fraction |
| Access transistor | NMOS width and length, threshold voltage, transconductance parameter KP |
| Drivers and timing | Wordline-high voltage, driver on-resistance, timing scale factor |

Use the **experiment presets** to quickly compare a weak cell, heavy bitline, weak transistor, low wordline drive, or slow peripheral drivers with the baseline. The ideal charge-sharing reference values and exported `.cir` file are regenerated from these settings. Previously plotted waveforms are identified as stale when controls are changed until you rerun ngspice.

## Design optimization

The **Automatic circuit optimization** section runs three bounded, reproducible algorithms:

1. Random search
2. Coordinate search
3. Differential evolution

Choose a target: **Balanced**, **Maximum sensing margin**, **Low switching energy**, or **Fast read access**. You can set a minimum sensing margin, maximum switching-energy proxy, maximum RC-delay proxy, upper VDD and wordline-voltage limits, and candidate-evaluation budget. The optimizer searches seven design variables; the NMOS process parameters and timing scale remain fixed to your selected values. Default voltage limits are 1.1 V VDD and 1.8 V wordline-high; these are educational design constraints, not a foundry reliability guarantee.

The algorithms initially rank candidates using a simplified analytical **surrogate**. With the validation checkbox on, the application executes ngspice on the three finalists and reports their *measured read margin*. It flags unverified or constraint-violating results. Use **Apply these values** to transfer the recommended design to the parameter controls, then run a full transient plot.

The search score is a relative engineering tradeoff, **not** proof of a globally perfect design or a manufacturing-ready DDR5 cell. Energy, delay, and area values are first-order proxies; high-fidelity device characterization, timing constraints, extracted parasitics, retention and signal integrity are future milestones.

Run the offline tests with:

```bash
python -m unittest test_optimizer.py test_sense_amplifier.py
```

## Files

- `streamlit_app.py` — interface, parameterized SPICE netlist and simulation runner
- `optimizer.py` — bounded multi-algorithm design search and tradeoff score
- `test_optimizer.py` — regression tests for search and surrogate behavior
- `sense_amplifier.py` — Lesson 3 SPICE generator, isolated cloud runner and waveform checks
- `pages/2_Sense_Amplifier.py` — mobile-friendly Step 3 experiment page
- `test_sense_amplifier.py` — verification, charge-sharing and circuit-structure tests
- `requirements.txt` — Python packages
- `packages.txt` — Linux package for Streamlit Community Cloud (`ngspice`)

## Deploy to Streamlit Community Cloud

1. Use the repository `muneebaq/ddr5-ngspice-streamlit` containing these files (including the `pages/` folder).
2. Open https://share.streamlit.io and sign in, connecting the GitHub account.
3. Click **Create app** and choose the repository, branch `main`, and entrypoint `streamlit_app.py`.
4. Deploy. Community Cloud installs the Python requirements and the system `ngspice` package.
5. Open your assigned `*.streamlit.app` URL from your phone.

See [Streamlit's deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy) and [system-package guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

## Local run on Linux (optional)

Install ngspice from the distribution package manager, then:

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Security and scope

The public web application **does not execute arbitrary uploaded SPICE netlists**. It generates a fixed, bounded educational circuit from slider values and invokes ngspice with `subprocess.run` (no shell, 35-second timeout). This avoids exposing shell-capable ngspice control features to untrusted users.

The transistor model, peripheral drivers, wordline boost, and storage capacitor are simplified for education. Results are not JEDEC compliance measurements, validated physical DDR5 device models, or predictions for an entire 32 GB module.
