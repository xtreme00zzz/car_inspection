from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .validator import ValidationResult


def _icon(ok: bool) -> str:
    return '✔' if ok else '✘'


def format_report_text(result: ValidationResult) -> str:
    lines: List[str] = []
    info = result.info

    def status_label(flag: Any) -> str:
        if flag is None:
            return 'N/A'
        return 'OK' if bool(flag) else 'INVALID'

    lines.append("eF Drift Car Scrutineer Report")
    lines.append("")
    matched = result.matched_reference or 'None'
    lines.append(f"Matched Reference: {matched}")
    lines.append(f"Exact Physics Match: {'YES' if result.exact_physics_match else 'NO'}")
    submitted_name = info.get('submitted_car_name')
    if submitted_name:
        name_valid = info.get('submitted_car_name_valid')
        expected_prefix = info.get('expected_car_name_prefix')
        suffix = f" (requires '{expected_prefix}' prefix)" if expected_prefix else ''
        temp_note = " (temporary extract)" if info.get('submitted_car_name_temp') else ''
        lines.append(f"Submitted Car Folder: {submitted_name} [{status_label(name_valid)}]{suffix}{temp_note}")
    ui_disp_name = info.get('ui_car_name')
    if ui_disp_name:
        lines.append(f"UI Display Name: {ui_disp_name} [{status_label(info.get('ui_car_name_valid'))}]")
    screen_name = info.get('car_ini_screen_name')
    if screen_name:
        lines.append(f"car.ini SCREEN_NAME: {screen_name} [{status_label(info.get('car_ini_screen_name_valid'))}]")
    kn5_files = info.get('kn5_files') or []
    kn5_checked = info.get('kn5_checked') or []
    if kn5_files:
        kn5_flag = info.get('kn5_prefix_valid') if kn5_checked else None
        kn5_status = status_label(kn5_flag)
        detail = f"{len(kn5_files)} total; {len(kn5_checked)} checked (excl. collider/driver)"
        lines.append(f"KN5 Filenames: {kn5_status} ({detail})")
    overall_ok = result.exact_physics_match and not result.rule_violations
    lines.append(f"Overall Status: {'PASS' if overall_ok else 'FAIL'}")
    lines.append("")
    # Key checks summary
    vlist = result.rule_violations or []
    def no_violation(sub: str) -> bool:
        return not any(sub in v for v in vlist)
    section_icons: Dict[str, str] = {
        'Key Checks': '📋',
        'Violations': '⚠',
        'Physics Mismatches (grouped)': '🛠',
        'Vehicle Specs': '🚗',
        'Gearing Overview': '⚙',
        'KN5 Files': '🗂',
        'Skins Breakdown': '🎨',
        'Textures': '🖼',
        'Setup Locked Items (min==max)': '🔒',
        'Setup Range Issues': '🔧',
        'Data Hash Mismatches': '🔐',
        'Data Modification Analysis': '📝',
        'Extension Folder Review': '🧩',
        'Root Folder Differences': '📁',
        'Suspicious Root Entries': '🚩',
        'Anti-Cheat': '🛡',
    }
    def push_section(title: str, *, suffix: str = '', icon: str | None = None, colon: bool = True) -> None:
        label = title.rstrip(':')
        icon_char = icon if icon is not None else section_icons.get(label)
        header = f"{icon_char} {label}" if icon_char else label
        if suffix:
            header += suffix
        if colon and not header.endswith(':'):
            header += ':'
        if lines and lines[-1] != '':
            lines.append('')
        lines.append(header)

    dtype = info.get('drivetrain')
    total_mass = info.get('total_mass')
    fb = info.get('front_bias')
    ftw = info.get('front_tyre_width_mm')
    rtw = info.get('rear_tyre_width_mm')
    steer = info.get('measured_wheel_angle_deg')
    if steer is None and isinstance(info.get('cm_steer'), dict):
        try:
            v = info['cm_steer'].get('max_wheel_angle_deg')
            if v is not None:
                steer = round(abs(float(v)), 2)
        except Exception:
            steer = info['cm_steer'].get('max_wheel_angle_deg')
    push_section("Key Checks")
    lines.append(f"- {_icon(result.exact_physics_match)} Physics exact match")
    if submitted_name:
        expected_prefix = info.get('expected_car_name_prefix')
        prefix_note = f" (req '{expected_prefix}' prefix)" if expected_prefix else ''
        lines.append(f"- {_icon(bool(info.get('submitted_car_name_valid')))} Car folder name: {submitted_name}{prefix_note}")
    if ui_disp_name:
        lines.append(f"- {_icon(bool(info.get('ui_car_name_valid')))} UI display name: {ui_disp_name}")
    if screen_name:
        lines.append(f"- {_icon(bool(info.get('car_ini_screen_name_valid')))} car.ini SCREEN_NAME: {screen_name}")
    if kn5_files:
        kn5_valid = info.get('kn5_prefix_valid')
        kn5_checked = info.get('kn5_checked') or []
        invalid_kn5 = info.get('kn5_prefix_violations') or []
        checked_count = len(kn5_checked)
        detail = f"{checked_count} checked (excludes collider/driver); {len(kn5_files)} total"
        if invalid_kn5:
            detail += f"; check {', '.join(invalid_kn5[:3])}"
            if len(invalid_kn5) > 3:
                detail += f" (+{len(invalid_kn5)-3} more)"
        icon_flag = True if kn5_valid is None else bool(kn5_valid)
        lines.append(f"- {_icon(icon_flag)} KN5 filenames use prefix ({detail})")
    lines.append(f"- {_icon((dtype or '').upper()=='RWD')} Drivetrain: {dtype}")
    exp_mass = info.get('expected_min_total_mass_kg')
    if exp_mass is not None and total_mass is not None:
        lines.append(f"- {_icon(no_violation('TOTALMASS'))} Mass: {total_mass} kg (min {exp_mass} kg)")
    exp_fb = info.get('expected_front_bias')
    if exp_fb is not None and fb is not None:
        lines.append(f"- {_icon(no_violation('Front bias'))} Front bias: {fb} (exp {exp_fb:.3f}±0.005)")
    exp_fr = info.get('expected_front_tyre_range_mm')
    if exp_fr and ftw is not None:
        lines.append(f"- {_icon(no_violation('Front tyre WIDTH'))} Front tyre: {ftw} mm (exp {exp_fr[0]}-{exp_fr[1]} mm)")
    exp_rmax = info.get('expected_rear_tyre_max_mm')
    if exp_rmax is not None and rtw is not None:
        lines.append(f"- {_icon(no_violation('Rear tyre WIDTH'))} Rear tyre: {rtw} mm (max {exp_rmax} mm)")
    exp_steer = info.get('expected_max_steer_angle_deg')
    if exp_steer is not None and steer is not None:
        ref_angle = info.get('reference_steer_angle_deg')
        delta = info.get('steer_reference_delta')
        line = f"- {_icon(no_violation('wheel angle'))} Steering angle: {steer}°"
        try:
            if ref_angle is not None:
                line += f" vs ref {float(ref_angle):.2f}°"
                if delta is not None:
                    line += f" (Δ {float(delta):+0.2f}°)"
        except Exception:
            pass
        line += f" (max {exp_steer}°)"
        lines.append(line)
    if info.get('expected_max_kn5_mb') is not None:
        limit = info.get('expected_max_kn5_mb')
        kn5_sizes = info.get('kn5_sizes') or {}
        largest = None
        largest_name = None
        try:
            if kn5_sizes:
                largest_name, largest = max(kn5_sizes.items(), key=lambda kv: float(kv[1] or 0.0))
                largest = float(largest)
        except Exception:
            largest = None
        try:
            limit_val = float(limit) if limit is not None else None
        except Exception:
            limit_val = None
        if largest is not None and limit_val is not None:
            lines.append(f"- {_icon(no_violation('KN5 file'))} KN5 sizes: {largest:.1f} MB (max {limit_val:.1f} MB)")
        elif limit_val is not None:
            lines.append(f"- {_icon(no_violation('KN5 file'))} KN5 sizes within max {limit_val:.1f} MB")
        else:
            lines.append(f"- {_icon(no_violation('KN5 file'))} KN5 sizes within limit")
    if info.get('expected_max_skin_mb') is not None:
        lines.append(f"- {_icon(no_violation('Largest skin'))} Skin sizes within limit")
    if info.get('expected_max_triangles') is not None or info.get('expected_max_objects') is not None:
        lines.append(f"- {_icon(no_violation('Total triangles') and no_violation('Total objects'))} Model triangles/objects within limit")
    skins_count = info.get('skins_count')
    if skins_count is not None:
        lines.append(f"- {_icon(skins_count == 1)} Skins: {skins_count} (expected 1)")
    lines.append("")
    # Violations and mismatches detail
    if result.rule_violations:
        push_section("Violations")
        for v in result.rule_violations:
            lines.append(f"- {v}")
    if not result.exact_physics_match:
        push_section("Physics Mismatches (grouped)")
        # Group by file/section
        grouped: Dict[Tuple[str,str], List[Tuple[str,str,str]]] = {}
        for m in result.physics_mismatches:
            # Expected format: fname[sec] opt: submitted='v' != ref='v'
            try:
                fname, rest = m.split('[', 1)
                sec, tail = rest.split(']', 1)
                opt = tail.split(':', 1)[0].strip()
                sub = ''
                ref = ''
                if "submitted=" in tail and "ref=" in tail:
                    after = tail.split(':',1)[1]
                    parts = after.split("ref=")
                    sub = parts[0].strip().replace("submitted=", '').strip(" '")
                    ref = parts[1].strip().strip(" '")
                key = (fname.strip(), sec.strip())
                grouped.setdefault(key, []).append((opt, sub, ref))
            except Exception:
                # Fallback to raw line
                lines.append(f"- {m}")
        for (fname, sec), items in grouped.items():
            lines.append(f"- {fname} [{sec}]")
            for opt, sub, ref in items:
                lines.append(f"    • {opt}: '{sub}' vs '{ref}'")
    # Detailed vehicle specifications
    _spec_keys = (
        'drivetrain','total_mass','steer_lock','steer_ratio','derived_wheel_angle_deg',
        'wheelbase','front_track','rear_track','front_bias','fuel_tank_pos',
        'ui_power_curve','power_curve','power_peak','cm_steer','sim_steer','kn5_stats'
    )
    if any(k in result.info and result.info.get(k) not in (None, '') for k in _spec_keys):
        push_section("Vehicle Specs")
    if 'drivetrain' in result.info:
        lines.append(f"- Drivetrain: {result.info['drivetrain']}")
    if 'total_mass' in result.info:
        mass_line = f"- Total Mass: {result.info['total_mass']} kg"
        exp = result.info.get('expected_min_total_mass_kg')
        if exp is not None:
            mass_line += f" (min {exp} kg)"
        lines.append(mass_line)
    if 'steer_lock' in result.info or 'steer_ratio' in result.info:
        s_lock = result.info.get('steer_lock')
        s_ratio = result.info.get('steer_ratio')
        details = []
        if s_lock is not None:
            details.append(f"STEER_LOCK {s_lock}")
        if s_ratio is not None:
            details.append(f"STEER_RATIO {s_ratio}")
        lines.append("- Steering Controls: " + ", ".join(details))
    if 'derived_wheel_angle_deg' in result.info:
        ang = result.info['derived_wheel_angle_deg']
        exp = result.info.get('expected_max_steer_angle_deg')
        line = f"- Derived Max Wheel Angle (approx): {ang}°"
        if exp is not None:
            line += f" (max {exp}°)"
        lines.append(line)
    if 'wheelbase' in result.info:
        lines.append(f"- Wheelbase: {result.info['wheelbase']} m")
    if 'front_track' in result.info and 'rear_track' in result.info:
        lines.append(f"- Track F/R: {result.info['front_track']} m / {result.info['rear_track']} m")
    if 'front_bias' in result.info:
        fb = result.info['front_bias']
        exp = result.info.get('expected_front_bias')
        if exp is not None:
            lines.append(f"- Front Bias (CG_LOCATION): {fb} (expected {exp:.3f}±0.005)")
        else:
            lines.append(f"- Front Bias (CG_LOCATION): {fb}")
    if 'fuel_tank_pos' in result.info and result.info['fuel_tank_pos']:
        lines.append(f"- Fuel Tank Position: {result.info['fuel_tank_pos']}")
    # Curves summary (concise, no ASCII art)
    try:
        p_peak = None
        if 'ui_power_curve' in result.info:
            p_peak = result.info['ui_power_curve'].get('max')
        elif 'power_curve' in result.info:
            p_peak = result.info['power_curve'].get('max')
        elif 'power_peak' in result.info:
            p_peak = result.info['power_peak'].get('power')
        if p_peak is not None:
            lines.append(f"- Power peak: {p_peak} hp")
    except Exception:
        pass
    third_ratio = result.info.get('third_gear_overall')
    final_ratio = result.info.get('final_drive_ratio')
    if third_ratio is not None or final_ratio is not None:
        push_section("Gearing Overview")
        if final_ratio is not None:
            rng = result.info.get('drift_final_ratio_range') or (3.4, 4.6)
            lines.append(f"- Final drive ratio: {final_ratio:.2f} (target {rng[0]:.1f}-{rng[1]:.1f})")
        if third_ratio is not None:
            rng = result.info.get('drift_third_ratio_range') or (2.4, 3.6)
            lines.append(f"- 3rd gear overall: {third_ratio:.2f} (target {rng[0]:.1f}-{rng[1]:.1f})")
    try:
        t_peak = None
        if 'ui_torque_curve' in result.info:
            t_peak = result.info['ui_torque_curve'].get('max')
        elif 'torque_curve' in result.info:
            t_peak = result.info['torque_curve'].get('max')
        if t_peak is not None:
            lines.append(f"Torque peak: {int(t_peak)} Nm")
    except Exception:
        pass
    if 'kn5_files' in result.info and result.info['kn5_files']:
        files = result.info['kn5_files']
        exp_kn5_mb = result.info.get('expected_max_kn5_mb')
        suffix = ''
        if exp_kn5_mb is not None:
            suffix = f" (max {exp_kn5_mb} MB each)"
        push_section("KN5 Files", suffix=suffix)
        sizes = result.info.get('kn5_sizes') or {}
        for name in files:
            sz = sizes.get(name)
            if isinstance(sz, (int, float)):
                lines.append(f"- {name}: {sz:.1f} MB")
            else:
                lines.append(f"- {name}")
    if 'max_skin' in result.info and result.info['max_skin']:
        ms = result.info['max_skin']
        skin_line = f"Largest Skin: {ms['name']} ({ms['size_mb']:.1f} MB)"
        exp_skin = result.info.get('expected_max_skin_mb')
        if exp_skin is not None:
            skin_line += f" (max {exp_skin} MB)"
        lines.append(skin_line)
    if 'skins_sizes' in result.info:
        ss = result.info['skins_sizes'] or {}
        if ss:
            push_section("Skins Breakdown")
            for k in sorted(ss.keys()):
                lines.append(f"- {k}: {ss[k]:.1f} MB")
    # Tyre widths summary, include expectations
    if 'front_tyre_width_mm' in result.info or 'rear_tyre_width_mm' in result.info:
        ftw = result.info.get('front_tyre_width_mm')
        rtw = result.info.get('rear_tyre_width_mm')
        exp_range = result.info.get('expected_front_tyre_range_mm')
        exp_rear_max = result.info.get('expected_rear_tyre_max_mm')
        if ftw is not None:
            if isinstance(exp_range, (list, tuple)) and len(exp_range) == 2:
                lines.append(f"Front Tyre Width: {ftw} mm (expected {exp_range[0]}-{exp_range[1]} mm)")
            else:
                lines.append(f"Front Tyre Width: {ftw} mm")
        if rtw is not None:
            if exp_rear_max is not None:
                lines.append(f"Rear Tyre Width: {rtw} mm (max {exp_rear_max} mm)")
            else:
                lines.append(f"Rear Tyre Width: {rtw} mm")
    if skins_count is not None:
        lines.append(f"Skins: {skins_count} (expected 1)")
    if 'cm_steer' in result.info or 'sim_steer' in result.info:
        try:
            data = result.info.get('cm_steer') or result.info.get('sim_steer')
            if isinstance(data, dict):
                if 'max_wheel_angle_deg' in data:
                    try:
                        ang = round(abs(float(data['max_wheel_angle_deg'])), 2)
                    except Exception:
                        ang = data['max_wheel_angle_deg']
                    src = str(data.get('source') or 'CM').upper()
                    if src == 'INI_DERIVED':
                        src = 'INI'
                    elif src == 'DERIVED':
                        src = 'DERIVED'
                    elif src in ('NORMALIZED', 'NORMALIZED_LOW'):
                        src = 'CM normalized'
                    line = f"Measured Max Wheel Angle: {ang}° ({src})"
                    ref_angle = result.info.get('reference_steer_angle_deg')
                    delta = result.info.get('steer_reference_delta')
                    exp = result.info.get('expected_max_steer_angle_deg')
                    try:
                        if ref_angle is not None:
                            line += f" vs ref {float(ref_angle):.2f}°"
                            if delta is not None:
                                line += f" (Δ {float(delta):+0.2f}°)"
                    except Exception:
                        pass
                    if exp is not None:
                        line += f" (max {exp}°)"
                    lines.append(line)
                elif 'left_max_deg' in data and 'right_max_deg' in data:
                    try:
                        l = round(abs(float(data['left_max_deg'])), 2)
                    except Exception:
                        l = data['left_max_deg']
                    try:
                        r = round(abs(float(data['right_max_deg'])), 2)
                    except Exception:
                        r = data['right_max_deg']
                    src = str(data.get('source') or 'CM').upper()
                    if src == 'INI_DERIVED':
                        src = 'INI'
                    elif src == 'DERIVED':
                        src = 'DERIVED'
                    elif src in ('NORMALIZED', 'NORMALIZED_LOW'):
                        src = 'CM normalized'
                    # If inner/outer available (simulated), present both and a max summary
                    inner = data.get('inner_deg')
                    outer = data.get('outer_deg')
                    if inner is not None and outer is not None:
                        try:
                            inner_v = round(abs(float(inner)), 2)
                        except Exception:
                            inner_v = inner
                        try:
                            outer_v = round(abs(float(outer)), 2)
                        except Exception:
                            outer_v = outer
                        try:
                            max_v = round(max(float(l), float(r)), 2)
                        except Exception:
                            max_v = l
                        line = f"Simulated Steering: inner {inner_v}° / outer {outer_v}° — max {max_v}° ({src})"
                    else:
                        line = f"Measured Max Wheel Angle: L {l}° / R {r}° ({src})"
                    exp = result.info.get('expected_max_steer_angle_deg')
                    if exp is not None:
                        line += f" (max {exp}°)"
                    lines.append(line)
        except Exception:
            pass
    if 'kn5_stats' in result.info:
        ks = result.info['kn5_stats']
        if isinstance(ks, dict):
            if 'total_triangles' in ks and 'total_objects' in ks:
                line = f"KN5 Stats: {ks['total_triangles']} triangles, {ks['total_objects']} objects"
                exp_t = result.info.get('expected_max_triangles')
                exp_o = result.info.get('expected_max_objects')
                suffix = []
                if exp_t is not None:
                    suffix.append(f"triangles max {exp_t}")
                if exp_o is not None:
                    suffix.append(f"objects max {exp_o}")
                if suffix:
                    line += f" ({', '.join(suffix)})"
                lines.append(line)
            elif 'files' in ks and isinstance(ks['files'], list):
                total_tris = sum(int(f.get('triangles', 0)) for f in ks['files'])
                total_objs = sum(int(f.get('objects', 0)) for f in ks['files'])
                line = f"KN5 Stats: {total_tris} triangles, {total_objs} objects (sum)"
                exp_t = result.info.get('expected_max_triangles')
                exp_o = result.info.get('expected_max_objects')
                suffix = []
                if exp_t is not None:
                    suffix.append(f"triangles max {exp_t}")
                if exp_o is not None:
                    suffix.append(f"objects max {exp_o}")
                if suffix:
                    line += f" ({', '.join(suffix)})"
                lines.append(line)

    # Texture audit summary
    textures = result.info.get('textures') or []
    if textures:
        offenders = [t for t in textures if (t.get('w', 0) > 4096 or t.get('h', 0) > 4096)]
        push_section("Textures", suffix=f" ({len(textures)} files)")
        if offenders:
            lines.append("Large textures (>4096px):")
            for t in offenders[:10]:
                lines.append(f"- {t['file']}: {int(t.get('w',0))}x{int(t.get('h',0))} ({t['size_mb']:.1f} MB)")
            if len(offenders) > 10:
                lines.append(f"... and {len(offenders)-10} more")

    # Setup locks
    if 'setup_locked' in result.info:
        locked = result.info.get('setup_locked') or []
        if locked:
            push_section("Setup Locked Items (min==max)")
            for sec in locked:
                lines.append(f"- {sec}")
    setup_range_issues = result.info.get('setup_range_issues') or []
    if setup_range_issues:
        push_section("Setup Range Issues")
        for msg in setup_range_issues[:20]:
            lines.append(f"- {msg}")

    hash_mismatches = result.info.get('hash_mismatches') or []
    if hash_mismatches:
        push_section("Data Hash Mismatches")
        for item in hash_mismatches[:20]:
            path = item.get('path') or 'unknown'
            exp = (item.get('expected') or '')[:8]
            act = (item.get('actual') or '')[:8]
            lines.append(f"- {path} (exp {exp}… got {act}…)")
        if len(hash_mismatches) > 20:
            lines.append(f"... and {len(hash_mismatches)-20} more")

    data_mods = result.info.get('data_modifications') or []
    if data_mods:
        push_section("Data Modification Analysis")
        for mod in data_mods[:10]:
            path = mod.get('path', 'unknown')
            severity = mod.get('severity', 'unknown')
            lines.append(f"- {path} (severity: {severity})")
            for change in (mod.get('changes') or [])[:5]:
                sec = change.get('section')
                key = change.get('key')
                detail = change.get('detail')
                if key:
                    lines.append(f"    · [{sec}] {key}: {detail or ''} ref={change.get('reference')} new={change.get('value')} delta={change.get('delta')}")
                else:
                    lines.append(f"    · {detail}")
            if len(mod.get('changes') or []) > 5:
                lines.append(f"    · ... and {len(mod['changes'])-5} more")
        if len(data_mods) > 10:
            lines.append(f"- ... and {len(data_mods)-10} more modifications")

    ext_summary = result.info.get('extension_summary') or {}
    if ext_summary:
        push_section("Extension Folder Review")
        status = ext_summary.get('status') or 'unknown'
        lines.append(f"- Status: {status}")
        expected = ext_summary.get('expected')
        if expected and status == 'missing':
            lines.append("- Reference expects extension configs, but folder is missing")
        file_count = ext_summary.get('file_count')
        if file_count is not None:
            lines.append(f"- Files scanned: {file_count}")
        physics_count = ext_summary.get('physics_count', 0)
        physics_details = ext_summary.get('physics_details') or []
        if physics_count:
            shown_details = physics_details[:10]
            lines.append(f"- Suspected physics overrides ({physics_count}):")
            for item in shown_details:
                f = item.get('file') or 'unknown'
                reason = item.get('reason')
                if reason:
                    lines.append(f"  · {f} — {reason}")
                else:
                    lines.append(f"  · {f}")
            physics_list = ext_summary.get('physics') or []
            if physics_list and len(physics_list) > len(shown_details):
                remaining = len(physics_list) - len(shown_details)
                if remaining > 0:
                    lines.append(f"  · ... and {remaining} more")
        unknown_count = ext_summary.get('unknown_count', 0)
        unknown_items = ext_summary.get('unknown') or []
        if unknown_count:
            lines.append(f"- Unknown items ({unknown_count}) — manual review suggested")
            for item in unknown_items[:10]:
                lines.append(f"  · {item}")
            if len(unknown_items) > 10:
                lines.append(f"  · ... and {len(unknown_items)-10} more")
        cosmetic_sample = ext_summary.get('cosmetic_sample') or []
        cosmetic_count = ext_summary.get('cosmetic_count')
        if cosmetic_sample:
            sample_len = len(cosmetic_sample)
            total = cosmetic_count if cosmetic_count is not None else sample_len
            lines.append(f"- Cosmetic sample ({sample_len} of {total}):")
            for item in cosmetic_sample[:10]:
                lines.append(f"  · {item}")
            if sample_len > 10:
                lines.append(f"  · ... and {sample_len-10} more")
        files = ext_summary.get('files') or []
        if status == 'cosmetic' and files:
            lines.append(f"- All files cosmetic (listing first 10 of {len(files)}):")
            for f in files[:10]:
                lines.append(f"  · {f}")
            if len(files) > 10:
                lines.append(f"  · ... and {len(files)-10} more")
        hash_deltas = result.info.get('extension_hash_mismatches') or []
        if hash_deltas:
            lines.append(f"- Differs from reference hashes ({len(hash_deltas)} file{'s' if len(hash_deltas)!=1 else ''})")
            for path in hash_deltas[:10]:
                lines.append(f"  · {path}")
            if len(hash_deltas) > 10:
                lines.append(f"  · ... and {len(hash_deltas)-10} more")

    root_extra_dirs = result.info.get('root_extra_dirs') or []
    root_missing_dirs = result.info.get('root_missing_dirs') or []
    root_extra_files = result.info.get('root_extra_files') or []
    root_missing_files = result.info.get('root_missing_files') or []
    if root_extra_dirs or root_missing_dirs or root_extra_files or root_missing_files:
        push_section("Root Folder Differences")
        if root_extra_dirs:
            lines.append(f"- Extra directories ({len(root_extra_dirs)}):")
            for d in root_extra_dirs[:10]:
                lines.append(f"  · {d}")
            if len(root_extra_dirs) > 10:
                lines.append(f"  · ... and {len(root_extra_dirs)-10} more")
        if root_missing_dirs:
            lines.append(f"- Missing directories ({len(root_missing_dirs)}):")
            for d in root_missing_dirs[:10]:
                lines.append(f"  · {d}")
            if len(root_missing_dirs) > 10:
                lines.append(f"  · ... and {len(root_missing_dirs)-10} more")
        if root_extra_files:
            lines.append(f"- Extra files ({len(root_extra_files)}):")
            for f in root_extra_files[:10]:
                lines.append(f"  · {f}")
            if len(root_extra_files) > 10:
                lines.append(f"  · ... and {len(root_extra_files)-10} more")
        if root_missing_files:
            lines.append(f"- Missing files ({len(root_missing_files)}):")
            for f in root_missing_files[:10]:
                lines.append(f"  · {f}")
            if len(root_missing_files) > 10:
                lines.append(f"  · ... and {len(root_missing_files)-10} more")
    suspicious_dirs = result.info.get('root_suspicious_dirs') or []
    suspicious_files = result.info.get('root_suspicious_files') or []
    if suspicious_dirs or suspicious_files:
        push_section("Suspicious Root Entries")
        if suspicious_dirs:
            lines.append(f"- Directories: {', '.join(suspicious_dirs[:10])}")
            if len(suspicious_dirs) > 10:
                lines.append(f"  · ... and {len(suspicious_dirs)-10} more")
        if suspicious_files:
            lines.append(f"- Files: {', '.join(suspicious_files[:10])}")
            if len(suspicious_files) > 10:
                lines.append(f"  · ... and {len(suspicious_files)-10} more")

    # Anti-cheat aggregate (avoid duplication with items already covered above)
    ac = result.info.get('anti_cheat')
    if ac:
        # Skip IDs that duplicate sections already printed in the report
        skip_ids = {
            'AC007',  # Drivetrain RWD (in Key Checks)
            'AC008', 'AC009',  # Tyre widths (already summarized)
            'AC015',  # Colliders extents (violations listed)
            'AC016',  # Model caps (printed in KN5 Stats)
            'AC017',  # KN5 sizes (covered by KN5 sizes section)
            'AC018',  # Skins count
        }
        pruned = [i for i in ac if (i.get('id') or '') not in skip_ids]
        if pruned:
            status_icon_map = {'pass': '✅', 'fail': '🛑', 'warn': '⚠️'}
            push_section("Anti-Cheat")
            for item in pruned:
                status = str(item.get('status') or '').lower()
                icon = status_icon_map.get(status, '⚠️')
                ident = item.get('id') or ''
                label = item.get('label') or ''
                detail = item.get('detail') or ''
                base = f"- [{ident}] {icon} {label}"
                if detail:
                    base += f" — {detail}"
                lines.append(base)

    return "\n".join(lines) + "\n"


def save_report(result: ValidationResult, out_dir: Path, base_name: str, to_json: bool = False) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    text_path = out_dir / f"{base_name}.txt"
    text_path.write_text(format_report_text(result), encoding='utf-8')
    if to_json:
        json_path = out_dir / f"{base_name}.json"
        json_path.write_text(json.dumps({
            'matched_reference': result.matched_reference,
            'exact_physics_match': result.exact_physics_match,
            'physics_mismatches': result.physics_mismatches,
            'rule_violations': result.rule_violations,
            'info': result.info,
        }, indent=2), encoding='utf-8')
    return text_path
