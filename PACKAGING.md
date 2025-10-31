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
- Upload a suitable asset for the chosen channel:
  - Stable: prefer the one‑file EXE named `eF Drift Car Scrutineer.exe`. To reduce size for GitHub limits, you can set `NO_REF_DATA=1` when building.
  - Alternatively, upload the installer `efdrift-scrutineer-setup.exe` and the app will launch it directly.
- On startup, the app checks for updates based on `UPDATE_CHANNEL` and prompts to install newer versions.

Private repos and tokens
------------------------

- For private repos, set an environment variable with a GitHub token on the client machine so the updater can read releases:
  - `EF_SCRUTINEER_GITHUB_TOKEN` (preferred) or `GITHUB_TOKEN`
  - Token needs at least `repo` read access.

Direct URL override (advanced)
------------------------------

- You can bypass GitHub Releases for updates by setting an environment variable to a direct download URL:
  - `EF_SCRUTINEER_UPDATE_URL` or channel‑specific `EF_SCRUTINEER_UPDATE_URL_STABLE` / `_BETA` / `_ALPHA`
- The updater will download that URL and, if the file name contains `setup` or `installer`, it will launch it; otherwise it will attempt in‑place replacement.
