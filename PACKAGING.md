eF Drift Car Scrutineer — Public Packaging
==========================================

Overview
--------

This guide describes how to build the public (stable) Windows distributions of the eF Drift Car Scrutineer desktop app.

Prerequisites
-------------

- Windows environment with Python and PyInstaller available in a virtual env (e.g., `.venv-win` or the existing `.venv-alpha-win`) using `build/requirements-alpha.txt`.
- Reference data in `reference_cars/`.

Build Steps
----------

1. Set the version and channel in `app_version.py`:
   - `APP_VERSION = "X.Y.Z"`
   - `UPDATE_CHANNEL = "stable"`
2. From a developer command prompt, run:
   - `build\win_build_release.bat`
3. Outputs (under `dist\`):
   - `eF Drift Car Scrutineer\` — one‑dir build
   - `eF Drift Car Scrutineer.exe` — one‑file build
   - `release_payload\` — release folder containing app, EXE, `VERSION.txt`, docs, and the updater stub

Updates and Releases
--------------------

- Create a GitHub Release tagged with the version (e.g., `v1.0.0` or `1.0.0`).
- Upload the one‑file EXE named `eF Drift Car Scrutineer.exe` to the release.
- On startup, the app checks for updates based on `UPDATE_CHANNEL` and prompts to install newer versions.
