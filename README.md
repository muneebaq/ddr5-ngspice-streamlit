# DDR5 Research Lab — Cloud ngspice on Streamlit

A mobile-friendly Streamlit app that runs **real ngspice transient simulations** of a simplified 1T1C DRAM cell on the cloud server. The browser acts only as a client, so an Android phone or iPhone needs no ngspice installation.

## Files

- `streamlit_app.py` — interface, parameterized SPICE netlist and simulation runner
- `requirements.txt` — Python packages
- `packages.txt` — Linux package for Streamlit Community Cloud (`ngspice`)

## Deploy to Streamlit Community Cloud

1. Create a GitHub repository and upload these three files to its root.
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
