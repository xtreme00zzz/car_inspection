# Alpha Packaging Guide

This document covers how to produce the public Windows installer for the
alpha release of the eF Drift Car Scrutineer.

## 1. Prerequisites

1. Windows 10/11 build workstation with PowerShell 7+.
2. Python 3.11 or newer on `PATH`.
3. Visual C++ Build Tools (for compiling any compiled wheels if needed).
4. Inno Setup 6.x installed and its `ISCC.exe` added to `PATH`.
5. Optional but recommended: a clean Python virtual environment dedicated to
   the build.

Install Python dependencies:

```powershell
python -m venv .venv-alpha
.venv-alpha\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r build\requirements-alpha.txt
```

## 2. Generate the Standalone Executable

Run the helper script which wraps PyInstaller and collects runtime assets:

```powershell
pwsh -File build\build_alpha_dist.ps1
```

The script produces:

- `dist\eF Drift Car Scrutineer Alpha\` – PyInstaller directory build.
- `dist\eF Drift Car Scrutineer Alpha.exe` – single-file bootstrap executable.
- `dist\alpha_payload\` – folder copied verbatim into the installer, containing
  reference cars, configuration defaults, and documentation.

## 3. Build the Installer

Use Inno Setup to compile the installer script with the freshly produced
artifacts:

```powershell
iscc.exe build\installer_alpha.iss
```

The installer binary (e.g. `dist\eF-Car-Scrutineer-Alpha-Setup.exe`) lands in
`dist\` by default. Adjust the output path in the `.iss` file if you prefer a
different location.

## 4. Smoke Test

1. Run the generated installer in a clean VM (or Windows Sandbox).
2. Confirm that:
   - The program installs under `%ProgramFiles%\eF Drift Car Scrutineer Alpha`.
   - Shortcuts for the app and manual appear in the Start Menu.
   - Launching the app works, icons display correctly, and the initial
     inspection flow succeeds.
3. Verify the shipped `reference_cars` set matches the intended alpha bundle.

## 5. Release Checklist

- Update `build\alpha_release_notes.txt` with changes since the last drop.
- Increment the `AlphaVersion` constant in `build_alpha_dist.ps1` if needed.
- Tag the repository (e.g. `alpha-2024.04`).
- Publish installer + release notes to the distribution channel.
