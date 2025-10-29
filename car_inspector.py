#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
from typing import Any, Dict
import datetime

from inspector.reference_index import build_reference_index, save_index, load_index
from inspector.matcher import build_fingerprint_index
from inspector.validator import validate_submitted_car, RulebookConfig
from inspector.report import save_report
from inspector.csv_export import write_summary_csv
from inspector.junit import write_junit_xml

CONFIG_PATH = Path('.cache/cm_config.json')


def cmd_build_index(args: argparse.Namespace) -> None:
    ref_root = Path(args.reference_root)
    out = Path(args.out)
    print(f"Indexing reference cars from {ref_root} ...")
    idx = build_reference_index(ref_root)
    save_index(idx, out)
    # Also store fingerprints for exact comparison
    fp_idx = build_fingerprint_index(ref_root)
    save_index(fp_idx, out.with_suffix('.fingerprints.json'))
    print(f"Saved index to {out} and fingerprints to {out.with_suffix('.fingerprints.json')}")


def cmd_inspect(args: argparse.Namespace) -> None:
    submitted = Path(args.car)
    idx_path = Path(args.index)
    fp_path = Path(args.fingerprints)
    out_dir = Path(args.report_dir)
    name = args.name or submitted.name

    print(f"Loading reference index from {idx_path} ...")
    ref_idx = load_index(idx_path)
    print(f"Loading fingerprints from {fp_path} ...")
    fp_idx = load_index(fp_path)

    # Ruleset preset (competition) with override by explicit flags
    preset = {}
    if args.ruleset == 'competition':
        # Allow environment-provided auto-generation commands for zero manual steps
        cm_cmd_env = os.getenv('CM_STEER_CMD') or 'powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\cm_steer_from_ini.ps1 -Car "{car}" -Out "{out}"'
        ks_cmd_env = os.getenv('KS_STATS_CMD') or 'powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\ks_stats_from_ui.ps1 -Car "{car}" -Out "{out}"'
        preset = dict(
            min_year=1965,
            enforce_rwd=True,
            min_total_mass_kg=1300.0,
            enforce_front_bias=0.52,
            enforce_rear_tyre_max_mm=265,
            enforce_front_tyre_range_mm=(225, 265),
            max_kn5_mb=60,
            max_skin_mb=30,
            max_steer_angle_deg=70.0,
            # Require files if we can auto-generate them (env-provided commands)
            require_cm_steer_file=bool(cm_cmd_env),
            require_kn5_stats_file=bool(ks_cmd_env),
            cm_steer_cmd=cm_cmd_env,
            ks_stats_cmd=ks_cmd_env,
            max_triangles=500_000,
            max_objects=300,
            fallback_reference_key='vdc_bmw_e92_public',
        )

    def choose(val, key, default=None):
        return val if val is not None else preset.get(key, default)

    # Determine auto-generation commands (CLI overrides env/preset)
    cm_cmd = args.cm_steer_cmd or preset.get('cm_steer_cmd')
    ks_cmd = args.ks_stats_cmd or preset.get('ks_stats_cmd')

    rb = RulebookConfig(
        enforce_body_types=args.enforce_body_tags,
        min_year=preset.get('min_year', 1965),
        enforce_rwd=True,
        enforce_front_engine=False,  # cannot auto-detect reliably
        min_total_mass_kg=choose(args.enforce_min_mass, 'min_total_mass_kg'),
        enforce_front_bias=choose(args.enforce_front_bias, 'enforce_front_bias'),
        enforce_rear_tyre_max_mm=choose(args.enforce_rear_tyre_max, 'enforce_rear_tyre_max_mm'),
        enforce_front_tyre_range_mm=tuple(args.enforce_front_tyre_range) if args.enforce_front_tyre_range else preset.get('enforce_front_tyre_range_mm'),
        max_kn5_mb=choose(args.max_kn5_mb, 'max_kn5_mb', 60),
        max_skin_mb=choose(args.max_skin_mb, 'max_skin_mb', 30),
        max_triangles=choose(args.max_triangles, 'max_triangles'),
        max_objects=choose(args.max_objects, 'max_objects'),
        max_steer_angle_deg=choose(args.max_steer_angle, 'max_steer_angle_deg'),
        # Hard-require when an auto-generation command is present, or explicitly requested
        require_cm_steer_file=args.require_cm_data or bool(cm_cmd),
        require_kn5_stats_file=args.require_kn5_stats or bool(ks_cmd),
        cm_steer_cmd=cm_cmd,
        ks_stats_cmd=ks_cmd,
        fallback_reference_key=('vdc_bmw_e92_public' if args.e92_fallback else preset.get('fallback_reference_key')),
    )

    print(f"Validating submitted car at {submitted} ...")
    result = validate_submitted_car(submitted, fp_idx, ref_idx, rb)
    rp = save_report(result, out_dir, name, to_json=args.json)
    print(f"Report saved to {rp}")
    if not result.exact_physics_match:
        print("Exact physics match: FAILED")
    if result.rule_violations:
        print("Rule violations detected:")
        for v in result.rule_violations:
            print(f" - {v}")
    # Append to history
    try:
        hist = out_dir / 'history.jsonl'
        row = {
            'ts': datetime.datetime.utcnow().isoformat() + 'Z',
            'car': name,
            'report': str(rp),
            'matched_reference': result.matched_reference,
            'exact_physics_match': result.exact_physics_match,
            'violations': result.rule_violations,
        }
        with hist.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def cmd_inspect_batch(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    idx_path = Path(args.index)
    fp_path = Path(args.fingerprints)
    out_dir = Path(args.report_dir)
    print(f"Loading index from {idx_path} and fingerprints from {fp_path}")
    ref_idx = load_index(idx_path)
    fp_idx = load_index(fp_path)
    rows = []
    # Rulebook from flags (competition baseline)
    rb = RulebookConfig(
        enforce_body_types=False,
        min_year=1965,
        enforce_rwd=True,
        enforce_front_engine=False,
        min_total_mass_kg=1300.0,
        enforce_front_bias=0.52,
        enforce_rear_tyre_max_mm=265,
        enforce_front_tyre_range_mm=(225, 265),
        max_kn5_mb=60,
        max_skin_mb=30,
        max_triangles=500_000,
        max_objects=300,
        max_steer_angle_deg=70.0,
        require_cm_steer_file=True,
        require_kn5_stats_file=True,
    )

    print(f"Batch inspecting cars in {root} ...")
    for car in sorted([p for p in root.iterdir() if p.is_dir()]):
        try:
            name = car.name
            res = validate_submitted_car(car, fp_idx, ref_idx, rb)
            save_report(res, out_dir, name, to_json=args.json)
            overall_ok = res.exact_physics_match and not res.rule_violations
            info = res.info
            rows.append({
                'car': name,
                'matched_reference': res.matched_reference,
                'exact_physics_match': res.exact_physics_match,
                'overall_pass': overall_ok,
                'violations_count': len(res.rule_violations or []),
                'drivetrain': info.get('drivetrain'),
                'total_mass': info.get('total_mass'),
                'front_bias': info.get('front_bias'),
                'front_tyre_mm': info.get('front_tyre_width_mm'),
                'rear_tyre_mm': info.get('rear_tyre_width_mm'),
                'steering_deg': (info.get('cm_steer') or {}).get('max_wheel_angle_deg'),
                'skins_count': info.get('skins_count'),
                'triangles': (info.get('kn5_stats') or {}).get('total_triangles'),
            })
        except Exception as e:
            print(f"Error inspecting {car}: {e}")
        # Append to history
        try:
            hist = out_dir / 'history.jsonl'
            row = {
                'ts': datetime.datetime.utcnow().isoformat() + 'Z',
                'car': name,
                'report': str((out_dir / f"{name}.txt")),
                'matched_reference': res.matched_reference if 'res' in locals() else None,
                'exact_physics_match': res.exact_physics_match if 'res' in locals() else None,
                'violations': res.rule_violations if 'res' in locals() else [str(e)],
            }
            with hist.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass
    csv_path = out_dir / 'summary.csv'
    write_summary_csv(csv_path, rows)
    print(f"Wrote CSV summary to {csv_path}")
    # JUnit XML
    cases = []
    for r in rows:
        cases.append({
            'name': r.get('car'),
            'passed': bool(r.get('overall_pass')),
            'violations': [],
        })
    write_junit_xml(out_dir / 'junit.xml', 'Inspection', cases)
    print(f"Wrote JUnit XML to {out_dir / 'junit.xml'}")


def cmd_gen_cm_steer(args: argparse.Namespace) -> None:
    car = Path(args.car)
    out = Path(args.out)
    # Prefer explicit command, else env, else derived
    cmd = args.cm_steer_cmd or os.getenv('CM_STEER_CMD')
    out.parent.mkdir(parents=True, exist_ok=True)
    if cmd:
        final = cmd.format(car=str(car), out=str(out))
        print(f"Running: {final}")
        os.system(final)
        if out.exists():
            print(f"Wrote {out}")
            return
        print("External command did not produce output; falling back to derived approximation")
    # Derived approximation using data
    from inspector.ini_parser import read_ini
    from inspector.ini_parser import get_float as _gf
    try:
        car_ini = read_ini(car / 'data' / 'car.ini')
        steer_lock = _gf(car_ini, 'CONTROLS', 'STEER_LOCK') or 0.0
        steer_ratio = _gf(car_ini, 'CONTROLS', 'STEER_RATIO') or 0.0
        derived = steer_lock / steer_ratio if steer_ratio else 0.0
    except Exception:
        derived = 0.0
    data = {"max_wheel_angle_deg": round(derived, 2), "source": "derived"}
    out.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f"Wrote derived steering JSON to {out}")


def cmd_gen_ks_stats(args: argparse.Namespace) -> None:
    car = Path(args.car)
    out = Path(args.out)
    cmd = args.ks_stats_cmd or os.getenv('KS_STATS_CMD')
    out.parent.mkdir(parents=True, exist_ok=True)
    if cmd:
        final = cmd.format(car=str(car), out=str(out))
        print(f"Running: {final}")
        os.system(final)
        if out.exists():
            print(f"Wrote {out}")
            return
        print("External command did not produce output; falling back to best-effort estimation")
    # Best-effort estimation: try cm_lods_generation.json if present
    import json as _json
    ui = car / 'ui' / 'cm_lods_generation.json'
    total_triangles = None
    total_objects = None
    if ui.exists():
        try:
            raw = _json.loads(ui.read_text(encoding='utf-8', errors='ignore'))
            stages = raw.get('Stages', {})
            tris = 0
            cnt = 0
            for k, v in stages.items():
                if isinstance(v, str):
                    v = _json.loads(v)
                t = int(v.get('trianglesCount', 0))
                if t > 0:
                    tris += t
                    cnt += 1
            if tris > 0:
                total_triangles = tris
        except Exception:
            pass
    # As a fallback for objects: count top-level meshes from names in lods.ini is not possible; leave None
    payload = {}
    if total_triangles is not None:
        payload['total_triangles'] = total_triangles
    if total_objects is not None:
        payload['total_objects'] = total_objects
    # If no data available, write empty structure to signal missing stats
    if not payload:
        payload = {"note": "stats unavailable; provide KS_STATS_CMD for exact counts"}
    out.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(f"Wrote KN5 stats JSON to {out}")


def set_cm_config(args: argparse.Namespace) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            cfg = {}
    if getattr(args, 'set_exe', None):
        cfg['cm_exe'] = args.set_exe
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
        print(f"Saved Content Manager path to {CONFIG_PATH}")
    else:
        print("No --set-exe provided. Current config:")
        print(json.dumps(cfg, indent=2))


def _to_windows_path(path: Path) -> str:
    p = str(path)
    if p.startswith('/mnt/') and len(p) > 6:
        drive = p[5].upper()
        rest = p[7:]
        return f"{drive}:\\{rest.replace('/', '\\')}"
    return p


def open_in_cm(args: argparse.Namespace) -> None:
    car = Path(args.car).resolve()
    cm_exe = getattr(args, 'cm_exe', None) or os.getenv('CM_EXE')
    if not cm_exe and CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
            cm_exe = cfg.get('cm_exe')
        except Exception:
            pass
    # Attempt discovery if requested
    if not cm_exe and getattr(args, 'find', False):
        candidates = [
            'C:\\Program Files (x86)\\Content Manager\\Content Manager.exe',
            'C:\\Program Files\\Content Manager\\Content Manager.exe',
            'C:\\Program Files (x86)\\Steam\\steamapps\\common\\assettocorsa\\content manager\\Content Manager.exe',
            'C:\\Program Files\\Steam\\steamapps\\common\\assettocorsa\\content manager\\Content Manager.exe',
        ]
        for c in candidates:
            if Path(c).exists():
                cm_exe = c
                break
    if not cm_exe:
        print("Content Manager not found. Use cm-config --set-exe or set CM_EXE env, or pass --cm-exe.")
        return
    car_win = _to_windows_path(car)
    print(f"Launching Content Manager: {cm_exe}")
    try:
        if os.name == 'nt':
            os.startfile(cm_exe)  # type: ignore
            # Open car folder
            os.startfile(car_win)  # type: ignore
        else:
            import subprocess, platform
            # Try to launch CM if provided
            subprocess.Popen([cm_exe])
            # Open folder in default file manager
            system = platform.system()
            if system == 'Darwin':
                subprocess.Popen(['open', str(car)])
            else:
                subprocess.Popen(['xdg-open', str(car)])
    except Exception as e:
        print(f"Failed to launch CM or open folder: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Assetto Corsa Car Inspector")
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_idx = sub.add_parser('build-index', help='Build reference index')
    p_idx.add_argument('--reference-root', default='reference_cars', help='Path to reference cars root')
    p_idx.add_argument('--out', default='.cache/reference_index.json', help='Path to write index JSON')
    p_idx.set_defaults(func=cmd_build_index)

    p_ins = sub.add_parser('inspect-car', help='Inspect a submitted car folder')
    p_ins.add_argument('--ruleset', choices=['competition', 'none'], default='none', help='Apply a predefined ruleset (competition applies provided rulebook)')
    p_ins.add_argument('car', help='Path to submitted car folder')
    p_ins.add_argument('--index', default='.cache/reference_index.json', help='Reference index JSON')
    p_ins.add_argument('--fingerprints', default='.cache/reference_index.fingerprints.json', help='Reference fingerprints JSON')
    p_ins.add_argument('--report-dir', default='reports', help='Directory to write reports')
    p_ins.add_argument('--name', default=None, help='Base name for report files')
    p_ins.add_argument('--json', action='store_true', help='Also write JSON report')
    p_ins.add_argument('--enforce-body-tags', action='store_true', help='Enforce body type tags from UI')
    p_ins.add_argument('--enforce-min-mass', type=float, default=None, help='Enforce minimum TOTALMASS in kg')
    p_ins.add_argument('--enforce-rear-tyre-max', type=int, default=None, help='Enforce maximum rear tyre width in mm')
    p_ins.add_argument('--enforce-front-tyre-range', type=int, nargs=2, metavar=('MIN','MAX'), default=None, help='Enforce front tyre width range in mm')
    p_ins.add_argument('--enforce-front-bias', type=float, default=None, help='Enforce front bias CG_LOCATION value (e.g., 0.52)')
    p_ins.add_argument('--max-kn5-mb', type=int, default=None, help='Max allowed kn5 file size in MB')
    p_ins.add_argument('--max-skin-mb', type=int, default=None, help='Max allowed skin folder size in MB')
    p_ins.add_argument('--max-steer-angle', type=float, default=None, help='Max allowed measured front wheel angle in degrees (requires analysis/cm_steer.json)')
    p_ins.add_argument('--max-triangles', type=int, default=None, help='Max allowed total triangles (from analysis/kn5_stats.json)')
    p_ins.add_argument('--max-objects', type=int, default=None, help='Max allowed total objects (from analysis/kn5_stats.json)')
    p_ins.add_argument('--require-cm-data', action='store_true', help='Require analysis/cm_steer.json for steering validation')
    p_ins.add_argument('--require-kn5-stats', action='store_true', help='Require analysis/kn5_stats.json for model validation')
    p_ins.add_argument('--cm-steer-cmd', type=str, default=None, help='Command to auto-generate analysis/cm_steer.json (use {car} and {out} placeholders)')
    p_ins.add_argument('--ks-stats-cmd', type=str, default=None, help='Command to auto-generate analysis/kn5_stats.json (use {car} and {out} placeholders)')
    p_ins.add_argument('--e92-fallback', action='store_true', help="Allow exact physics fallback to 'vdc_bmw_e92_public' if no reference matches")
    p_ins.set_defaults(func=cmd_inspect)

    p_b = sub.add_parser('inspect-batch', help='Inspect all cars in a folder and write CSV summary')
    p_b.add_argument('root', help='Root folder containing car folders')
    p_b.add_argument('--index', default='.cache/reference_index.json', help='Reference index JSON')
    p_b.add_argument('--fingerprints', default='.cache/reference_index.fingerprints.json', help='Reference fingerprints JSON')
    p_b.add_argument('--report-dir', default='reports', help='Directory to write reports')
    p_b.add_argument('--json', action='store_true', help='Also write JSON report for each car')
    p_b.set_defaults(func=cmd_inspect_batch)

    # Optional: watch mode (polling)
    def cmd_watch(args: argparse.Namespace) -> None:
        import time
        from collections import defaultdict
        root = Path(args.root).resolve()
        last_mtime = defaultdict(float)
        print(f"Watching {root} for changes. Press Ctrl+C to stop.")
        while True:
            try:
                changed = []
                for car in [p for p in root.iterdir() if p.is_dir()]:
                    m = 0.0
                    for p in car.rglob('*'):
                        try:
                            m = max(m, p.stat().st_mtime)
                        except Exception:
                            pass
                    if m > last_mtime[car]:
                        last_mtime[car] = m
                        changed.append(car)
                for car in changed:
                    try:
                        print(f"Change detected in {car.name}; inspecting...")
                        # Reuse inspect-car logic quickly
                        args2 = argparse.Namespace(car=str(car), index=str(Path('.cache/reference_index.json')), fingerprints=str(Path('.cache/reference_index.fingerprints.json')), report_dir=args.report_dir, name=None, json=True, enforce_body_tags=False, enforce_min_mass=None, enforce_rear_tyre_max=None, enforce_front_tyre_range=None, enforce_front_bias=None, max_kn5_mb=None, max_skin_mb=None, max_steer_angle=None, max_triangles=None, max_objects=None, require_cm_data=False, require_kn5_stats=False, e92_fallback=True)
                        cmd_inspect(args2)
                    except Exception as e:
                        print(f"Failed watching {car}: {e}")
                time.sleep(5)
            except KeyboardInterrupt:
                print("Stopped watching.")
                break

    p_w = sub.add_parser('inspect-watch', help='Watch a folder and inspect on changes (polling)')
    p_w.add_argument('root', help='Root folder containing car folders')
    p_w.add_argument('--report-dir', default='reports', help='Directory to write reports')
    p_w.set_defaults(func=cmd_watch)

    # Export plain diffs for a single car (optional CLI)
    def cmd_export_diffs(args: argparse.Namespace) -> None:
        car = Path(args.car)
        ref_idx = load_index(Path(args.index))
        fp_idx = load_index(Path(args.fingerprints))
        # Run a quick validation to get matched ref and mismatches
        rb = RulebookConfig(min_year=1965, enforce_rwd=True)
        res = validate_submitted_car(car, fp_idx, ref_idx, rb)
        if not res.matched_reference:
            print('No matched reference; cannot export diffs')
            return
        ref_path = Path(ref_idx[res.matched_reference]['path']) / 'data'
        from inspector.plain_diff import unified_diff_text
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = set()
        for m in res.physics_mismatches or []:
            try:
                fname = m.split('[', 1)[0].strip()
                files.add(fname)
            except Exception:
                pass
        for fname in files:
            diff = unified_diff_text(car / 'data' / fname, ref_path / fname)
            (out_dir / f"{fname}.diff.txt").write_text(diff, encoding='utf-8')
        print(f"Wrote diffs for {len(files)} files to {out_dir}")

    p_ed = sub.add_parser('export-diffs', help='Export plain text diffs for mismatched physics')
    p_ed.add_argument('car', help='Path to submitted car folder')
    p_ed.add_argument('--index', default='.cache/reference_index.json', help='Reference index JSON')
    p_ed.add_argument('--fingerprints', default='.cache/reference_index.fingerprints.json', help='Reference fingerprints JSON')
    p_ed.add_argument('--out', default='reports/diffs', help='Output folder for plain diffs')
    p_ed.set_defaults(func=cmd_export_diffs)

    # Subcommand: configure Content Manager path
    p_cfg = sub.add_parser('cm-config', help='Configure Content Manager integration')
    p_cfg.add_argument('--set-exe', type=str, default=None, help='Path to Content Manager executable')
    p_cfg.set_defaults(func=lambda a: set_cm_config(a))

    # Subcommand: open car in Content Manager (best effort)
    p_open = sub.add_parser('open-in-cm', help='Open car in Content Manager (best effort)')
    p_open.add_argument('car', help='Path to submitted car folder')
    p_open.add_argument('--cm-exe', type=str, default=None, help='Path to Content Manager executable (overrides config/env)')
    p_open.add_argument('--find', action='store_true', help='Try to discover CM automatically on Windows')
    p_open.set_defaults(func=lambda a: open_in_cm(a))

    # Subcommand: generate CM steer JSON
    p_cm = sub.add_parser('gen-cm-steer', help='Generate analysis/cm_steer.json (uses command template or derived)')
    p_cm.add_argument('car', help='Path to submitted car folder')
    p_cm.add_argument('--out', default='analysis/cm_steer.json', help='Output JSON path (inside car dir by default)')
    p_cm.add_argument('--cm-steer-cmd', type=str, default=None, help='Command to auto-generate, uses {car} and {out}')
    p_cm.set_defaults(func=cmd_gen_cm_steer)

    # Subcommand: generate KN5 stats JSON
    p_ks = sub.add_parser('gen-ks-stats', help='Generate analysis/kn5_stats.json (uses command or UI LODs)')
    p_ks.add_argument('car', help='Path to submitted car folder')
    p_ks.add_argument('--out', default='analysis/kn5_stats.json', help='Output JSON path (inside car dir by default)')
    p_ks.add_argument('--ks-stats-cmd', type=str, default=None, help='Command to auto-generate, uses {car} and {out}')
    p_ks.set_defaults(func=cmd_gen_ks_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
