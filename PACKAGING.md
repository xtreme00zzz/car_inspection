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
- Recommended: host the large installer externally and attach a small manifest instead.
  - Run `build\publish_release.bat` to:
    1) Upload the installer to Cloudflare R2 (via AWS CLI)
    2) Generate `dist\update.json` with URL, size and sha256
    3) Create or update the GitHub Release and upload `update.json`
- On startup, the app checks for updates based on `UPDATE_CHANNEL` and prompts to install newer versions. The updater reads `update.json` from the release and downloads the installer from Cloudflare R2.

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

Cloudflare R2 setup
-------------------

- Create a bucket and make it publicly readable (via bucket policy) or front it with a public domain.
- Required env vars for publishing (used by `build\publish_release.bat`):
  - `R2_ACCOUNT_ID` — your Cloudflare Account ID
  - `R2_ACCESS_KEY_ID` — R2 S3 Access Key
  - `R2_SECRET_ACCESS_KEY` — R2 S3 Secret Key
  - `R2_BUCKET` — bucket name (e.g., `efdrift-updates`)
  - `R2_PUBLIC_BASE_URL` — public base URL (e.g., `https://updates.example.com`) — optional; if omitted, defaults to `https://{account}.r2.cloudflarestorage.com/{bucket}`
- Install AWS CLI and authenticate is not required globally; the script sets credentials via env for the one command:
  - `aws --endpoint-url https://{account}.r2.cloudflarestorage.com s3 cp file.exe s3://{bucket}/efdrift-scrutineer-setup.exe`
