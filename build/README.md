# Alpha Build Overview

This directory contains packaging assets for the distributable Windows build of
the eF Drift Car Scrutineer.

Artifacts:

- `requirements-alpha.txt` – pinned pip dependencies required on the build
  machine before running the packager.
- `car_inspection_alpha.spec` – PyInstaller spec used to generate the standalone
  executable.
- `build_alpha_dist.ps1` – Helper PowerShell script that drives PyInstaller and
  prepares artifacts for the installer stage.
- `installer_alpha.iss` – Inno Setup script that wraps the PyInstaller output in
  a Windows installer.
- `alpha_release_notes.txt` – Template release notes for the alpha drop.

Usage instructions live in the repository root `PACKAGING_ALPHA.md`.
