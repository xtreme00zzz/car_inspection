eF Drift Car Scrutineer — Beta Packaging Notes
=============================================

This document tracks packaging considerations for the beta milestone of the eF Drift Car Scrutineer desktop app. It largely mirrors the alpha checklist, with minor adjustments noted below.

PyInstaller Payload Contents
----------------------------

Include the following assets when building the beta release:

- `reference_cars/` — trimmed reference data generated via `build/prepare_alpha_reference.py`.
- `icon.ico` — application icon.
- `README.md` — user-facing instructions.
- `build/beta_release_notes.txt` — changelog for the beta drop.
- `PACKAGING_BETA.md` — this packaging guide (bundled under `docs/`).

Icon Refresh
------------

Regenerate the square EFVD taskbar icon before each release:

```
tools/generate_icon.sh
```

This script emits a `512x512` preview (`icon_preview.png`) and an updated multi-resolution `icon.ico`.

Build Process Overview
----------------------

1. Ensure the Windows packaging virtual environment (`.venv-alpha-win`) is updated with the latest dependencies from `build/requirements-alpha.txt`.
2. Run `build\win_build_beta.bat` from a developer command prompt. This script prepares trimmed reference assets, produces PyInstaller one-dir and one-file artifacts, assembles a distributable payload folder, and invokes Inno Setup if `iscc.exe` is available.
3. The resulting deliverables land in `dist\`:
   - `eF Drift Car Scrutineer Beta\` (one-dir build)
   - `eF Drift Car Scrutineer Beta.exe` (one-file build)
   - `beta_payload\` (installer staging folder with docs and executables)

Versioning & Notes
------------------

- Beta builds should increment the `VERSION.txt` payload tag to `BETA-x.y.z`.
- Document headline beta changes in `build/beta_release_notes.txt`. For the first beta cut, note the new enforced folder-naming rule for submitted cars.

Installer Branding
------------------

The existing `build/generate_branding_assets.py` script remains suitable. Run it as part of the build to refresh installer graphics that include the beta tag.

Automatic Update (Beta)
-----------------------

- Set the beta version in `app_version.py` (e.g., `APP_VERSION = "BETA-0.1.1"`). The beta build script stamps this into `dist\\beta_payload\\VERSION.txt`.
- Create a GitHub pre-release tagged with the same version string (e.g., `BETA-0.1.1`).
- Upload the one-file asset named `eF Drift Car Scrutineer Beta.exe` to the pre-release. The app prefers this asset for beta updates.
- On app launch, beta builds check for a newer pre-release and prompt users to download and run the update. Downloads are saved to `%LOCALAPPDATA%\\eFDriftScrutineer\\updates`.
