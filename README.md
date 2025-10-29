Car Inspector CLI
==================

Small CLI to validate submitted Assetto Corsa drift cars against a set of reference cars, and optionally enforce series rulebook constraints. It focuses on exact physics matching and produces a clear, human‑readable report.

Quick Start
-----------

1) Build the reference index

    python3 car_inspector.py build-index --reference-root reference_cars --out .cache/reference_index.json

This creates two files:

- .cache/reference_index.json — summary of reference cars
- .cache/reference_index.fingerprints.json — normalized physics fingerprints for exact matching

2) Inspect a submitted car folder

    python3 car_inspector.py inspect-car /path/to/submitted_car \
      --index .cache/reference_index.json \
      --fingerprints .cache/reference_index.fingerprints.json \
      --report-dir reports \
      --json

Ruleset Preset
--------------

Use `--ruleset competition` to apply the provided competition rulebook in one go:

- min mass 1300 kg; front bias CG_LOCATION 0.52
- rear tyre max 265 mm; front 225–265 mm
- steering angle max 70° (auto-generated if CM_STEER_CMD is set; otherwise derived from data and reported)
- KN5 <= 60 MB; skin <= 30 MB
- triangles <= 500k; objects <= 300 (auto-generated if KS_STATS_CMD is set; otherwise skipped)
- RWD required; year >= 1965; E92 physics fallback allowed

You can still override any of these via explicit flags.

The tool writes text and optional JSON reports to the reports/ directory.

What’s Checked
--------------

- Exact physics matching (strict):
  - data/car.ini — TOTALMASS, INERTIA, FUELTANK POSITION, controls, etc.
  - data/suspensions.ini — WHEELBASE, TRACK F/R, BASEY, toe, etc.
  - data/tyres.ini — compounds, widths, DX_REF/DY_REF, radii.
  - data/drivetrain.ini — TYPE (RWD), gear count/ratios, FINAL.
  - data/engine.ini — INERTIA, LIMITER, WASTEGATE, thresholds.
  - data/brakes.ini — FRONT_SHARE and related.
  - data/aero.ini — wings presence and fields.

- Rulebook extras (optional flags):
  - RWD enforcement (on by default).
  - Year >= 1965 based on ui/ui_car.json.
  - KN5 max size (default 60 MB) and largest skin size (default 30 MB).
  - Tyre width constraints (optional flags).
  - Fuel tank position realism heuristic.
  - Colliders size heuristics relative to track and wheelbase.
  - Steering angle via Content Manager export (analysis/cm_steer.json).
  - KN5 triangle/object counts via KS Editor/CM export (analysis/kn5_stats.json).

Notes & Limits
--------------

- Steering lock (70° at 0 toe) requires in‑game measurement. Configs don’t expose exact wheel angle limits.
- Front engine placement is not explicitly encoded in AC data; detection is left as manual unless a reliable field is provided.
- Triangle and object counts require KN5 parsing or Content Manager/KS Editor; if ui/cm_lods_generation.json is present, the tool reports target triangle counts but does not derive exact values from models.
- If a chassis lacks a reference, exact matching will fail. You can choose to require fallback to a specific reference (e.g., vdc_bmw_e92_public) as a competition policy.

Common Flags
------------

- --enforce-min-mass 1300
- --enforce-rear-tyre-max 265
- --enforce-front-tyre-range 225 265
- --max-kn5-mb 60
- --max-skin-mb 30
- --enforce-body-tags (uses ui/ui_car.json tags)
- --max-steer-angle 70 --require-cm-data (expects analysis/cm_steer.json)
- --require-kn5-stats (expects analysis/kn5_stats.json)
- --e92-fallback (exact physics fallback to vdc_bmw_e92_public)

Examples
--------

Validate a car with example rulebook limits on tyres and mass:

    python3 car_inspector.py inspect-car /path/to/car \
      --index .cache/reference_index.json \
      --fingerprints .cache/reference_index.fingerprints.json \
      --report-dir reports \
      --enforce-min-mass 1300 \
      --enforce-rear-tyre-max 265 \
      --enforce-front-tyre-range 225 265 \
      --json

Generate analysis files programmatically
---------------------------------------

- Option A: Use ruleset automation (env-based)
  - Set environment variables once:
    - Windows PowerShell:
      - `$env:CM_STEER_CMD = "powershell -ExecutionPolicy Bypass -File .\\tools\\templates\\cm_steer_template.ps1 -Car \"{car}\" -Out \"{out}\""`
      - `$env:KS_STATS_CMD = "powershell -ExecutionPolicy Bypass -File .\\tools\\templates\\ks_stats_template.ps1 -Car \"{car}\" -Out \"{out}\""`
  - Run with ruleset:
    - `python3 car_inspector.py inspect-car <car> --ruleset competition`

- Option B: Generate explicitly via CLI subcommands
  - `python3 car_inspector.py gen-cm-steer <car> --out analysis/cm_steer.json --cm-steer-cmd "powershell -ExecutionPolicy Bypass -File .\\tools\\templates\\cm_steer_template.ps1 -Car \"{car}\" -Out \"{out}\""`
  - `python3 car_inspector.py gen-ks-stats <car> --out analysis/kn5_stats.json --ks-stats-cmd "powershell -ExecutionPolicy Bypass -File .\\tools\\templates\\ks_stats_template.ps1 -Car \"{car}\" -Out \"{out}\""`

Content Manager / KS Editor Integration (Optional, zero manual export)
----------------------------------------------------------------------

- Auto-generate analysis files by providing command templates; the CLI will run them and read outputs (no manual export required):

  - Steering angle (0 toe):
    - Preferred built-in script (INI-derived):
      - CLI: `--cm-steer-cmd "powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\cm_steer_from_ini.ps1 -Car \"{car}\" -Out \"{out}\""`
      - ENV: `CM_STEER_CMD="powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\cm_steer_from_ini.ps1 -Car \"{car}\" -Out \"{out}\""`
      - This computes an approximation: STEER_LOCK / STEER_RATIO from data/car.ini and writes analysis/cm_steer.json.
    - Or integrate your own Content Manager tool that writes `max_wheel_angle_deg`.
    - Also set `--max-steer-angle 70` to enforce the limit.
    - The tool invokes the command to produce `analysis/cm_steer.json`.

  - KN5 stats:
    - Preferred built-in script (UI-based estimate):
      - CLI: `--ks-stats-cmd "powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\ks_stats_from_ui.ps1 -Car \"{car}\" -Out \"{out}\""`
      - ENV: `KS_STATS_CMD="powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\ks_stats_from_ui.ps1 -Car \"{car}\" -Out \"{out}\""`
      - This sums trianglesCount from ui/cm_lods_generation.json.
    - Or integrate your own KS Editor/CM tool that outputs total_triangles/total_objects JSON.
    - Optionally set `--max-triangles 500000 --max-objects 300`.
    - The tool invokes the command to produce `analysis/kn5_stats.json`.

Notes:
- With `--ruleset competition`, if CM_STEER_CMD/KS_STATS_CMD are set, the tool auto-runs them and requires the resulting files; otherwise it skips those strict checks and still validates exact physics, CG, tyres, sizes, etc. Steering angle is approximated from data and shown with the expected limit.

E92 Fallback Policy
-------------------

If a chassis-specific reference doesn’t exist, enable `--e92-fallback` to allow exact physics matching to `vdc_bmw_e92_public`. If the car doesn’t match any reference or the fallback, the report will list mismatches and flag a violation.

Operational Tips
----------------

- Require participants to submit unpacked data/ folders (or provide instructions to unpack data.acd via Content Manager).
- For model polygons/objects verification, use KS Editor or CM to export counts and attach a screenshot/log to the report; this tool will include any available LOD generation targets for context.
