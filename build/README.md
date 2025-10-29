# Release Build Overview

This directory contains packaging assets for the public Windows build of the eF Drift Car Scrutineer.

Artifacts:

- `requirements-alpha.txt` – pinned pip dependencies for the packaging environment (legacy name is fine).
- `win_build_release.bat` – Windows batch script that builds onedir and onefile EXEs and assembles a release payload.
- `generate_branding_assets.py` – Helper to refresh branding images for installers or docs.

See `PACKAGING.md` in the repository root for step‑by‑step instructions.
