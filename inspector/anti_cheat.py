from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .ini_parser import read_ini, get_float, get_str
from .lut_parser import read_lut


CHECK_HINTS: Dict[str, str] = {
    'AC001': 'Missing data/ folder prevents validating and running the submitted physics.',
    'AC002': 'Having data.acd alongside data/ can mask alternate physics; remove the archive or data/ overlay.',
    'AC003': 'Car must fingerprint-match an approved reference to qualify for the competition.',
    'AC004': 'data/ must include exactly the files from the matched reference; no extras or missing files.',
    'AC007': 'Competition rules require a rear-wheel-drive drivetrain.',
    'AC008': 'Front tyre width is outside the allowed competition range.',
    'AC009': 'Rear tyre width exceeds the 265 mm maximum requirement.',
    'AC010': 'Large spikes in power.lut indicate an unrealistic or tampered power curve.',
    'AC011': 'UI horsepower should match physics output within 15%; update UI or physics data.',
    'AC012': 'CSP extension scripts can override physics; review or remove extension overrides.',
    'AC013': 'At least one .kn5 model must be present in the car folder.',
    'AC014': 'Collider.kn5 is missing; accurate collision geometry is required.',
    'AC015': 'Collider extends beyond body bounds; adjust collider dimensions.',
    'AC016': 'Model triangles or object count exceeds competition caps; optimise the mesh.',
    'AC017': 'KN5 file size exceeds the allowed limit; reduce textures or geometry.',
    'AC018': 'Only one skin is permitted; remove additional skins.',
    'AC019': 'Aero CL values are out of realistic range; review aero.ini.',
    'AC020': 'Turbo reference pressure is excessive; verify boost tune.',
    'AC021': 'Hidden files found; remove hidden assets before submission.',
    'AC022': 'Hidden directories detected; they can mask alternate content.',
    'AC023': 'Suspicious characters in filenames can conceal files; rename cleanly.',
    'AC024': 'Nested archives may hide alternate physics; unpack or remove them.',
    'AC025': 'Case-insensitive duplicate filenames break servers; ensure unique names.',
    'AC026': 'Executable or script files are not allowed inside the submission.',
    'AC027': 'Zero-sized files indicate broken or placeholder assets; remove or replace them.',
    'AC028': 'Steering lock should be measured via CM; geometry or INI estimates are only provisional.',
    'AC029': 'Submitted steering angle must match the reference physics; large deltas suggest altered steering geometry.',
    'AC030': 'CSP extension configs can mask behaviour; disable or ship only approved visuals.',
    'AC031': 'Core data files must match the sanctioned reference hashes.',
    'AC032': 'Collider KN5 must match the reference to avoid collision exploits.',
    'AC033': 'Unexpected folders/files at car root can hide tools or scripts; keep submission minimal.',
}

__all__ = ['run_anti_cheat_checks', 'extend_with_hidden_checks', 'CHECK_HINTS']


def _result(id: str, label: str, status: str, detail: str = "", items: list[str] | None = None) -> Dict[str, Any]:
    if not detail:
        hint = CHECK_HINTS.get(id, '')
        if status != 'pass' and hint:
            detail = hint
    r = {"id": id, "label": label, "status": status, "detail": detail}
    if items:
        r["items"] = items
    return r


def run_anti_cheat_checks(car_root: Path, info: Dict[str, Any], rulebook: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    data_dir = car_root / 'data'
    acd = car_root / 'data.acd'

    # AC001: data folder present
    out.append(_result('AC001', 'data/ folder present', 'pass' if data_dir.exists() else 'fail', ''))
    # AC002: data.acd present alongside data (overlay risk)
    if acd.exists() and data_dir.exists():
        out.append(_result('AC002', 'data.acd present with data/', 'warn', 'AC will prefer data/ over data.acd'))
    else:
        out.append(_result('AC002', 'data.acd overlay', 'pass', ''))
    # AC003: exact physics match to known reference
    if info.get('matched_reference') or info.get('matched_reference') is not None:
        # handled outside; rely on ValidationResult
        out.append(_result('AC003', 'Exact physics match to reference', 'pass' if info.get('exact_physics_match', False) else 'fail', str(info.get('matched_reference'))))
    else:
        # No match found
        out.append(_result('AC003', 'Exact physics match to reference', 'fail', 'No match found'))
    # AC004: data files whitelist exact
    if 'data_files_ok' in info:
        if info.get('data_files_ok'):
            out.append(_result('AC004', 'Data files whitelist', 'pass', ''))
        else:
            extra = info.get('data_files_extra') or []
            missing = info.get('data_files_missing') or []
            out.append(_result('AC004', 'Data files whitelist', 'fail', f"extra={len(extra)} missing={len(missing)}"))

    # AC007: drivetrain RWD
    dtype = (info.get('drivetrain') or '').upper()
    if dtype:
        out.append(_result('AC007', 'Drivetrain RWD', 'pass' if dtype == 'RWD' else 'fail', dtype))

    # AC008/AC009: tyres width within expected
    ftw = info.get('front_tyre_width_mm'); rtw = info.get('rear_tyre_width_mm')
    frange = info.get('expected_front_tyre_range_mm')
    rmax = info.get('expected_rear_tyre_max_mm')
    if ftw is not None and isinstance(frange, (list, tuple)) and len(frange) == 2:
        lo, hi = frange
        status = 'pass' if (lo <= int(ftw) <= hi) else 'fail'
        out.append(_result('AC008', 'Front tyre width within range', status, f"{ftw} mm (exp {lo}-{hi})"))
    if rtw is not None and rmax is not None:
        status = 'pass' if int(rtw) <= int(rmax) else 'fail'
        out.append(_result('AC009', 'Rear tyre width <= max', status, f"{rtw} mm (max {rmax})"))

    # AC010: power.lut spikes (unrealistic jumps)
    try:
        lut = car_root / 'data' / 'power.lut'
        if lut.exists():
            curve = read_lut(lut)
            spikes = []
            for i in range(1, len(curve)):
                rpm = float(curve[i][0])
                prev = float(curve[i-1][1])
                cur = float(curve[i][1])
                if prev > 0:
                    delta = cur - prev
                    pct = delta / prev
                    if abs(pct) > 0.35:
                        direction = 'up' if delta > 0 else 'down'
                        spikes.append(f"{int(rpm)} rpm {direction} {pct*100:.1f}% (Δ {delta:+.1f} hp)")
            status = 'pass' if not spikes else 'warn'
            detail = f"spikes={len(spikes)}" + (f" | {'; '.join(spikes[:5])}" if spikes else '')
            out.append(_result('AC010', 'Power curve smoothness', status, detail, spikes[:20]))
    except Exception:
        pass

    # AC011: UI vs data power peak mismatch
    try:
        ui_p = (info.get('ui_power_curve') or {}).get('max')
        data_p = (info.get('power_curve') or {}).get('max')
        if ui_p and data_p:
            diff = abs(float(ui_p) - float(data_p))
            rel = diff / max(1.0, float(data_p))
            status = 'pass' if rel <= 0.15 else 'warn'
            out.append(_result('AC011', 'UI vs data power peak', status, f"ui={ui_p} data={data_p}"))
    except Exception:
        pass

    # AC012: CSP extension scripts present
    ext = car_root / 'extension'
    if ext.exists():
        ec = (ext / 'ext_config.ini').exists()
        lua = list(ext.glob('**/*.lua'))
        if ec or lua:
            out.append(_result('AC012', 'CSP extension scripts present', 'warn', f"ext_config={ec} lua_files={len(lua)}"))
        else:
            out.append(_result('AC012', 'CSP extension scripts present', 'pass', ''))
    else:
        out.append(_result('AC012', 'CSP extension scripts present', 'pass', ''))

    ext_summary = info.get('extension_summary') or {}
    if ext_summary:
        status = ext_summary.get('status') or 'unknown'
        files = ext_summary.get('files') or []
        extra = ext_summary.get('extra') or []
        missing = ext_summary.get('missing') or []
        mismatched = ext_summary.get('mismatched') or []
        expected = bool(ext_summary.get('expected'))
        detail_parts: List[str] = []
        if expected:
            detail_parts.append('reference whitelist defined')
        if files:
            detail_parts.append(f"files={len(files)}")
        if extra:
            detail_parts.append(f"extra={len(extra)}")
        if missing:
            detail_parts.append(f"missing={len(missing)}")
        if mismatched:
            detail_parts.append(f"mismatch={len(mismatched)}")
        detail = ' | '.join(detail_parts) if detail_parts else ''
        if status == 'match':
            out.append(_result('AC030', 'Extension configs review', 'warn', detail or 'Matches approved whitelist; review visuals only.'))
        elif status == 'unexpected':
            out.append(_result('AC030', 'Extension configs review', 'warn', detail or 'extension/ present but not whitelisted.'))
        elif status == 'missing':
            out.append(_result('AC030', 'Extension configs review', 'warn', detail or 'Expected extension configs missing.'))
        else:
            info_list = (extra or []) + (missing or []) + (mismatched or [])
            out.append(_result('AC030', 'Extension configs review', 'fail', detail or 'Extension configs differ from whitelist.', info_list[:50]))
    else:
        out.append(_result('AC030', 'Extension configs review', 'pass', 'No extension folder present.'))

    # AC013: KN5 present and collider present
    kn5s = [p for p in car_root.glob('*.kn5') if p.is_file()]
    out.append(_result('AC013', 'KN5 present', 'pass' if kn5s else 'fail', f"count={len(kn5s)}"))
    has_collider = any('collider' in p.name.lower() for p in kn5s)
    out.append(_result('AC014', 'Collider KN5 present', 'pass' if has_collider else 'warn', ''))

    # AC015: Colliders within extents (based on violations list)
    viols = [str(v) for v in (info.get('violations') or [])]
    coll_bad = any('Collider ' in v for v in viols)
    out.append(_result('AC015', 'Colliders within body extents', 'fail' if coll_bad else 'pass', ''))

    data_mods = info.get('data_modifications') or []
    if data_mods:
        paths = [m.get('path') for m in data_mods[:50] if m.get('path')]
        detail_bits = []
        high = sum(1 for m in data_mods if m.get('severity') == 'high')
        medium = sum(1 for m in data_mods if m.get('severity') == 'medium')
        low = sum(1 for m in data_mods if m.get('severity') == 'low')
        if high:
            detail_bits.append(f"high={high}")
        if medium:
            detail_bits.append(f"medium={medium}")
        if low:
            detail_bits.append(f"low={low}")
        detail = ' | '.join(detail_bits) if detail_bits else f"changes={len(data_mods)}"
        out.append(_result('AC031', 'Data file changes vs reference', 'fail', detail, paths))
    else:
        out.append(_result('AC031', 'Data file changes vs reference', 'pass', ''))

    if info.get('collider_hash_mismatch'):
        out.append(_result('AC032', 'Collider.kn5 hash matches reference', 'fail', 'Hash mismatch on collider.kn5'))
    else:
        out.append(_result('AC032', 'Collider.kn5 hash matches reference', 'pass', ''))

    extra_dirs = info.get('root_extra_dirs') or []
    missing_dirs = info.get('root_missing_dirs') or []
    extra_files = info.get('root_extra_files') or []
    missing_files = info.get('root_missing_files') or []
    suspicious_dirs = info.get('root_suspicious_dirs') or []
    suspicious_files = info.get('root_suspicious_files') or []
    if extra_dirs or missing_dirs or extra_files or missing_files or suspicious_dirs or suspicious_files:
        details: List[str] = []
        if extra_dirs:
            details.append(f"extra_dirs={len(extra_dirs)}")
        if missing_dirs:
            details.append(f"missing_dirs={len(missing_dirs)}")
        if extra_files:
            details.append(f"extra_files={len(extra_files)}")
        if missing_files:
            details.append(f"missing_files={len(missing_files)}")
        if suspicious_dirs:
            details.append(f"suspicious_dirs={len(suspicious_dirs)}")
        if suspicious_files:
            details.append(f"suspicious_files={len(suspicious_files)}")
        sample = (extra_dirs + missing_dirs + extra_files + missing_files + suspicious_dirs + suspicious_files)[:50]
        status = 'fail' if suspicious_dirs or suspicious_files else 'warn'
        out.append(_result('AC033', 'Root folder contents match reference', status, ' | '.join(details) or 'differences detected', sample))
    else:
        out.append(_result('AC033', 'Root folder contents match reference', 'pass', ''))

    # AC016: KN5 stats within caps (triangles/objects)
    ks = info.get('kn5_stats') or {}
    tri_max = getattr(rulebook, 'max_triangles', None)
    obj_max = getattr(rulebook, 'max_objects', None)
    tri = None; obj = None
    if isinstance(ks, dict):
        tri = ks.get('total_triangles'); obj = ks.get('total_objects')
    status = 'pass'
    det = []
    if isinstance(tri, int) and isinstance(tri_max, int) and tri > tri_max:
        status = 'fail'
        det.append(f"tri={tri}>{tri_max}")
    if isinstance(obj, int) and isinstance(obj_max, int) and obj > obj_max:
        status = 'fail'
        det.append(f"obj={obj}>{obj_max}")
    if tri is not None or obj is not None:
        out.append(_result('AC016', 'Model caps (triangles/objects)', status, ' '.join(det)))

    # AC017: KN5 sizes within limit (per-file)
    sizes = info.get('kn5_sizes') or {}
    size_max = getattr(rulebook, 'max_kn5_mb', None)
    if sizes and size_max is not None:
        big = [name for name, mb in sizes.items() if mb and float(mb) > float(size_max)]
        out.append(_result('AC017', 'KN5 file sizes', 'pass' if not big else 'fail', f"over={big}"))

    # AC018: Skins count == 1
    sc = info.get('skins_count')
    if sc is not None:
        out.append(_result('AC018', 'Skins count == 1', 'pass' if int(sc) == 1 else 'fail', f"count={sc}"))

    # AC019: Aero extremes
    aero = car_root / 'data' / 'aero.ini'
    if aero.exists():
        try:
            ap = read_ini(aero)
            cl = get_float(ap, 'WING_0', 'CL') or get_float(ap, 'DATA', 'CL')
            if cl is not None:
                out.append(_result('AC019', 'Aero CL reasonable', 'pass' if abs(float(cl)) < 4.0 else 'warn', f"CL={cl}"))
            else:
                out.append(_result('AC019', 'Aero CL reasonable', 'pass', ''))
        except Exception:
            out.append(_result('AC019', 'Aero CL reasonable', 'warn', 'parse error'))
    else:
        out.append(_result('AC019', 'Aero CL reasonable', 'pass', 'no aero.ini'))

    # AC020: Turbo/Boost extremes (ctrl_turbo*.ini)
    turbo_files = list((car_root / 'data').glob('ctrl_turbo*.ini'))
    if turbo_files:
        # naive scan for reference pressure > 2.0 bar equivalent in kPa (200kPa)
        high = False
        for tf in turbo_files:
            try:
                tp = read_ini(tf)
                ref = get_float(tp, 'TURBO', 'REFERENCE_PRESSURE')
                if ref and ref > 2.0:
                    high = True
            except Exception:
                pass
        out.append(_result('AC020', 'Turbo reference pressure reasonable', 'pass' if not high else 'warn', ''))
    else:
        out.append(_result('AC020', 'Turbo reference pressure reasonable', 'pass', 'no turbo ctrl'))

    # Hidden/suspicious file checks
    extend_with_hidden_checks(car_root, out)

    # AC028: Steering measurement source quality
    try:
        cm = info.get('cm_steer')
        sim = info.get('sim_steer')
        if isinstance(cm, dict) and 'max_wheel_angle_deg' in cm:
            out.append(_result('AC028', 'Steering measurement source', 'pass', 'CM measured'))
        elif isinstance(sim, dict):
            s = str(sim.get('source') or '').lower()
            if 'geometry' in s:
                out.append(_result('AC028', 'Steering measurement source', 'warn', 'Geometry simulated'))
            else:
                out.append(_result('AC028', 'Steering measurement source', 'warn', 'INI ratio estimated'))
        else:
            out.append(_result('AC028', 'Steering measurement source', 'warn', 'Unavailable'))
    except Exception:
        pass

    # AC029: Steering matches reference
    try:
        ref_angle = info.get('reference_steer_angle_deg')
        measured = info.get('measured_wheel_angle_deg') or info.get('derived_wheel_angle_deg')
        if ref_angle is not None and measured is not None:
            diff = abs(float(measured) - float(ref_angle))
            if diff <= 0.5:
                status = 'pass'
            elif diff <= 2.0:
                status = 'warn'
            else:
                status = 'fail'
            out.append(_result('AC029', 'Steering angle matches reference', status, f"Δ={diff:.2f}°"))
    except Exception:
        pass

    return out


def _is_hidden_name(name: str) -> bool:
    return name.startswith('.') or name.lower() in ('.ds_store', 'thumbs.db')


def extend_with_hidden_checks(car_root: Path, checks: List[Dict[str, Any]]) -> None:
    """Extend checks with hidden/suspicious file scans."""
    try:
        hidden_files: List[str] = []
        hidden_dirs: List[str] = []
        unicode_suspicious: List[str] = []
        archives: List[str] = []
        zero_sized: List[str] = []
        backups: List[str] = []
        scripts: List[str] = []
        caseless_map = {}
        caseless_dupes: List[str] = []

        def scan_dir(root: Path):
            for p in root.rglob('*'):
                try:
                    rel = str(p.relative_to(car_root))
                except Exception:
                    rel = str(p)
                name = p.name
                # hidden
                if _is_hidden_name(name):
                    if p.is_dir():
                        hidden_dirs.append(rel)
                    else:
                        hidden_files.append(rel)
                # suspicious unicode (control chars / zero-width)
                bad = False
                for ch in name:
                    o = ord(ch)
                    if o < 32:
                        bad = True; break
                    if ch in ('\u200b', '\u200c', '\u200d', '\uFEFF'):
                        bad = True; break
                if bad:
                    unicode_suspicious.append(rel)
                # archives
                if p.is_file() and p.suffix.lower() in ('.zip', '.7z', '.rar'):
                    archives.append(rel)
                # zero size
                if p.is_file():
                    try:
                        if p.stat().st_size == 0:
                            zero_sized.append(rel)
                    except Exception:
                        pass
                # backup copies
                low = name.lower()
                if low.endswith('~') or low.endswith('.bak') or low.endswith('.orig'):
                    backups.append(rel)
                # scripts/executables in data
                if p.is_file() and p.suffix.lower() in ('.bat', '.ps1', '.cmd', '.exe', '.dll', '.vbs', '.sh', '.lua', '.py', '.pyc'):
                    scripts.append(rel)
                # case-insensitive duplicates in data
                if p.is_file():
                    key = rel.lower()
                    if key in caseless_map and caseless_map[key] != rel:
                        caseless_dupes.append(rel)
                    else:
                        caseless_map[key] = rel

        scan_dir(car_root)
        # AC021: hidden files in car
        checks.append(_result('AC021', 'Hidden files present', 'pass' if not hidden_files else 'warn', f"count={len(hidden_files)}", hidden_files[:200]))
        # AC022: hidden directories in car
        checks.append(_result('AC022', 'Hidden directories present', 'pass' if not hidden_dirs else 'warn', f"count={len(hidden_dirs)}", hidden_dirs[:200]))
        # AC023: Suspicious unicode in filenames
        checks.append(_result('AC023', 'Suspicious filename characters', 'pass' if not unicode_suspicious else 'warn', f"count={len(unicode_suspicious)}", unicode_suspicious[:200]))
        # AC024: Nested archives present
        checks.append(_result('AC024', 'Nested archives present', 'pass' if not archives else 'warn', f"count={len(archives)}", archives[:200]))
        # AC025: Case-insensitive filename duplicates in data
        checks.append(_result('AC025', 'Case-insensitive filename duplicates', 'pass' if not caseless_dupes else 'warn', f"count={len(caseless_dupes)}", caseless_dupes[:200]))
        # AC026: Scripts/executables inside car
        checks.append(_result('AC026', 'Executable/script files present', 'pass' if not scripts else 'warn', f"count={len(scripts)}", scripts[:200]))
        # AC027: Zero-size files
        checks.append(_result('AC027', 'Zero-sized files present', 'pass' if not zero_sized else 'warn', f"count={len(zero_sized)}", zero_sized[:200]))

    except Exception:
        pass
