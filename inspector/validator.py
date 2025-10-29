from __future__ import annotations

import configparser
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ini_parser import read_ini, get_float, get_int, get_str, get_tuple_of_floats, list_kn5_files, folder_size_bytes
from .matcher import _collect_fingerprint, exact_compare_to_index
from .lut_parser import read_lut, peak_values
from .ascii_chart import sparkline
from .anti_cheat import run_anti_cheat_checks


def _sha1_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha1()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


_COSMETIC_SUFFIXES = {
    '.dds', '.png', '.jpg', '.jpeg', '.bmp', '.tga', '.gif',
    '.ini', '.cfg', '.txt', '.json', '.ini.disabled',
    '.wav', '.ogg', '.mp3', '.bank', '.kn5.json',
}

_PHYSICS_SCRIPT_SUFFIXES = {'.lua', '.py', '.dll', '.exe', '.bat', '.ps1'}
_PHYSICS_PATH_MARKERS = ('/data/', '\\data\\', '/physics', '\\physics', '/lua/', '\\lua\\')
_PHYSICS_KEYWORDS = (
    '[physics', 'extended_physics', 'enable_extended_physics', 'use_extended_physics',
    'physics_extension', 'extra_physics', 'physics.lr', 'physics_override',
    '[tyres', '[drivetrain', '[engine', '[suspensions', '[aero', 'torque_curve',
    'power_curve', 'wheel_rate', 'inertia=', 'final_ratio', 'gear_', 'steer_lock',
    'cg_location', 'tyre_pressure', 'wing_',
)
_PHYSICS_LUA_KEYWORDS = (
    'require(\"physics', 'ac.setcarphysics', 'ac.onphysicsstep', 'ac.ext_patch.physics',
    'applyextendedphysics', 'setextendedphysics', 'setcarparam', 'settyre',
)


def _classify_extension_entry(rel: str, path: Path) -> Tuple[str, Optional[str]]:
    rel_lower = rel.lower()
    name_lower = path.name.lower()
    suffix = '.ini.disabled' if name_lower.endswith('.ini.disabled') else path.suffix.lower()
    if any(marker in rel_lower for marker in _PHYSICS_PATH_MARKERS):
        return 'physics', 'data/physics path'
    if suffix in _PHYSICS_SCRIPT_SUFFIXES:
        if suffix == '.lua':
            try:
                text = path.read_text(encoding='utf-8', errors='ignore').lower()
            except Exception:
                text = ''
            if any(keyword in text for keyword in _PHYSICS_LUA_KEYWORDS):
                return 'physics', 'lua physics hook'
            return 'unknown', None
        return 'physics', f'script file ({suffix})'
    if suffix in {'.ini', '.cfg', '.txt', '.json', '.ini.disabled'}:
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
            if not text:
                text = path.read_text(encoding='latin-1', errors='ignore')
        except Exception:
            text = ''
        lower_text = text.lower()
        for keyword in _PHYSICS_KEYWORDS:
            if keyword in lower_text:
                return 'physics', f"keyword '{keyword.strip()}'"
        return 'cosmetic', None
    if suffix in _COSMETIC_SUFFIXES:
        return 'cosmetic', None
    return 'unknown', None


def _normalize_name(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ''


def _has_prefix(value: Any, prefix: str) -> bool:
    if not isinstance(value, str):
        return False
    return _normalize_name(value).lower().startswith(prefix.lower())


def _parse_number(val: str) -> Optional[float]:
    try:
        cleaned = str(val).strip().replace(',', '.')
        if cleaned.lower() in ('', 'nan'):
            return None
        return float(cleaned)
    except Exception:
        return None


def _severity_from_delta(delta: float, ref: float) -> str:
    try:
        ref_abs = abs(ref)
        if ref_abs > 1e-6:
            pct = abs(delta) / ref_abs
            if pct <= 0.02:
                return 'low'
            if pct <= 0.1:
                return 'medium'
            return 'high'
        else:
            if abs(delta) <= 0.01:
                return 'low'
            if abs(delta) <= 0.05:
                return 'medium'
            return 'high'
    except Exception:
        return 'high'


def _severity_rank(level: str) -> int:
    order = {'low': 0, 'medium': 1, 'high': 2}
    return order.get(level, 2)


def _analyze_ini_delta(sub_path: Path, ref_path: Path) -> Optional[Dict[str, Any]]:
    try:
        sub_ini = read_ini(sub_path)
        ref_ini = read_ini(ref_path)
    except Exception:
        return None
    changes: List[Dict[str, Any]] = []
    max_severity = 'low'

    def record(change: Dict[str, Any]):
        nonlocal max_severity
        changes.append(change)
        sev = change.get('severity')
        if isinstance(sev, str) and _severity_rank(sev) > _severity_rank(max_severity):
            max_severity = sev

    ref_sections = {sec.lower(): sec for sec in ref_ini.sections()}
    sub_sections = {sec.lower(): sec for sec in sub_ini.sections()}
    all_sections = sorted(set(ref_sections) | set(sub_sections))
    for sec_lower in all_sections:
        ref_sec = ref_sections.get(sec_lower)
        sub_sec = sub_sections.get(sec_lower)
        if ref_sec and not sub_sec:
            record({
                'section': ref_sec,
                'severity': 'high',
                'detail': 'Section removed',
            })
            continue
        if sub_sec and not ref_sec:
            record({
                'section': sub_sec,
                'severity': 'high',
                'detail': 'New section added',
            })
            continue
        if not ref_sec or not sub_sec:
            continue
        ref_items = {k.lower(): k for k in ref_ini[ref_sec]}
        sub_items = {k.lower(): k for k in sub_ini[sub_sec]}
        all_keys = sorted(set(ref_items) | set(sub_items))
        for key_lower in all_keys:
            ref_key = ref_items.get(key_lower)
            sub_key = sub_items.get(key_lower)
            if ref_key and not sub_key:
                record({
                    'section': sub_sec,
                    'key': ref_key,
                    'severity': 'high',
                    'detail': 'Key removed',
                    'reference': ref_ini[ref_sec].get(ref_key),
                })
                continue
            if sub_key and not ref_key:
                record({
                    'section': sub_sec,
                    'key': sub_key,
                    'severity': 'high',
                    'detail': 'Key added',
                    'value': sub_ini[sub_sec].get(sub_key),
                })
                continue
            if not ref_key or not sub_key:
                continue
            ref_val = ref_ini[ref_sec].get(ref_key)
            sub_val = sub_ini[sub_sec].get(sub_key)
            if ref_val == sub_val:
                continue
            ref_num = _parse_number(ref_val)
            sub_num = _parse_number(sub_val)
            if ref_num is not None and sub_num is not None:
                delta = sub_num - ref_num
                severity = _severity_from_delta(delta, ref_num)
                record({
                    'section': sub_sec,
                    'key': sub_key,
                    'severity': severity,
                    'reference': ref_num,
                    'value': sub_num,
                    'delta': delta,
                })
            else:
                severity = 'medium' if (ref_val or '').lower() == (sub_val or '').lower() else 'high'
                record({
                    'section': sub_sec,
                    'key': sub_key,
                    'severity': severity,
                    'reference': ref_val,
                    'value': sub_val,
                    'detail': 'String changed',
                })
    return {
        'path': str(sub_path.name),
        'severity': max_severity,
        'changes': changes,
    } if changes else None


@dataclass
class RulebookConfig:
    enforce_body_types: bool = False
    allowed_body_types: Tuple[str, ...] = ("coupe", "sedan", "convertible", "hatchback", "estate", "wagon", "ute")
    forbid_types: Tuple[str, ...] = ("truck", "suv")
    min_year: int = 1965
    max_doors: int = 5  # not easily detectable
    enforce_rwd: bool = True
    enforce_front_engine: bool = False  # cannot reliably auto-detect
    min_total_mass_kg: Optional[float] = None  # 1300 per example, disabled by default due to ref variance
    enforce_front_bias: Optional[float] = None  # e.g., 0.52 (from suspensions.ini:BASIC:CG_LOCATION)
    enforce_rear_tyre_max_mm: Optional[int] = None  # 265 per example; disabled due to refs using 285
    enforce_front_tyre_range_mm: Optional[Tuple[int, int]] = None  # (225,265)
    max_kn5_mb: Optional[int] = 60
    max_skin_mb: Optional[int] = 30
    max_triangles: Optional[int] = 500_000  # heuristic via cm_lods if available
    max_objects: Optional[int] = 300  # not available without KN5 parsing
    # Steering (Content Manager integration)
    max_steer_angle_deg: Optional[float] = None
    require_cm_steer_file: bool = False
    cm_steer_cmd: Optional[str] = None  # command template with {car} and {out}
    # KN5 stats (KS Editor/CM integration)
    require_kn5_stats_file: bool = False
    ks_stats_cmd: Optional[str] = None  # command template with {car} and {out}
    # Fallback reference key for exact physics (e.g., vdc_bmw_e92_public)
    fallback_reference_key: Optional[str] = None


@dataclass
class ValidationResult:
    matched_reference: Optional[str]
    exact_physics_match: bool
    physics_mismatches: List[str]
    rule_violations: List[str]
    info: Dict[str, Any]


def _bytes_to_mb(n: int) -> float:
    return n / (1024.0 * 1024.0)


def validate_submitted_car(submitted_car_root: Path,
                           fingerprint_index: Dict[str, Dict[str, Dict[str, str]]],
                           reference_index: Dict[str, Any],
                           rulebook: RulebookConfig) -> ValidationResult:
    # 1) Exact physics compare to reference
    submitted_fp = _collect_fingerprint(submitted_car_root)
    cmp = exact_compare_to_index(submitted_fp, fingerprint_index)

    # 2) Rulebook checks
    rule_violations: List[str] = []
    info: Dict[str, Any] = {}
    fuel_flag_messages: List[str] = []
    # Record expected thresholds for richer reporting
    info['expected_min_total_mass_kg'] = rulebook.min_total_mass_kg
    info['expected_front_bias'] = rulebook.enforce_front_bias
    info['expected_rear_tyre_max_mm'] = rulebook.enforce_rear_tyre_max_mm
    info['expected_front_tyre_range_mm'] = rulebook.enforce_front_tyre_range_mm
    info['expected_max_kn5_mb'] = rulebook.max_kn5_mb
    info['expected_max_skin_mb'] = rulebook.max_skin_mb
    info['expected_max_steer_angle_deg'] = rulebook.max_steer_angle_deg
    info['expected_require_cm_data'] = rulebook.require_cm_steer_file
    info['expected_require_kn5_stats'] = rulebook.require_kn5_stats_file
    info['expected_max_triangles'] = rulebook.max_triangles
    info['expected_max_objects'] = rulebook.max_objects
    info['expected_fallback_reference_key'] = rulebook.fallback_reference_key
    # Car naming convention (folder + metadata)
    expected_prefix = 'efvd'
    expected_prefix_display = expected_prefix.upper()
    submitted_name = submitted_car_root.name
    folder_valid = _has_prefix(submitted_name, expected_prefix)
    folder_lower = submitted_name.lower()
    folder_temp_markers = ('car_inspector_', 'tmp', 'temp', 'temp_', 'tmp_')
    folder_seems_temp = any(folder_lower.startswith(marker) for marker in folder_temp_markers)
    info['expected_car_name_prefix'] = expected_prefix_display
    info['submitted_car_name'] = submitted_name
    info['submitted_car_name_valid'] = folder_valid
    if folder_seems_temp:
        info['submitted_car_name_temp'] = True
    if not folder_valid:
        if folder_seems_temp:
            rule_violations.append(
                f"Submission folder '{submitted_name}' appears temporary; ensure the archive root folder is renamed to begin with '{expected_prefix_display}'."
            )
        else:
            rule_violations.append(f"Car folder name '{submitted_name}' must begin with '{expected_prefix_display}'")
    ref_first_compound: Optional[Dict[str, Any]] = None

    # UI checks
    ui_json = submitted_car_root / 'ui' / 'ui_car.json'
    ui: Dict[str, Any] = {}
    if ui_json.exists():
        try:
            import json
            ui = json.loads(ui_json.read_text(encoding='utf-8', errors='ignore'))
        except Exception:
            ui = {}
    info['ui'] = ui
    ui_name = None
    if isinstance(ui, dict):
        ui_name = ui.get('name')
    if isinstance(ui_name, str):
        info['ui_car_name'] = ui_name
        ui_name_valid = _has_prefix(ui_name, expected_prefix)
        info['ui_car_name_valid'] = ui_name_valid
        if not ui_name_valid:
            rule_violations.append(f"ui/ui_car.json name '{ui_name}' must begin with '{expected_prefix_display}'")
    else:
        info['ui_car_name_valid'] = False if ui_json.exists() else None
    # UI power/torque curves (preferred for display)
    try:
        if isinstance(ui, dict):
            ui_pc = ui.get('powerCurve')
            if isinstance(ui_pc, list) and ui_pc:
                ys = [float(p[1]) for p in ui_pc if isinstance(p, (list, tuple)) and len(p) >= 2]
                info['ui_power_curve'] = {
                    'unit': 'hp',
                    'max': max(ys) if ys else 0,
                    'spark': sparkline(ys, length=60),
                }
            ui_tc = ui.get('torqueCurve')
            if isinstance(ui_tc, list) and ui_tc:
                ys = [float(p[1]) for p in ui_tc if isinstance(p, (list, tuple)) and len(p) >= 2]
                info['ui_torque_curve'] = {
                    'unit': 'Nm',
                    'max': max(ys) if ys else 0,
                    'spark': sparkline(ys, length=60),
                }
    except Exception:
        pass

    # Year
    year = ui.get('year') if isinstance(ui, dict) else None
    if isinstance(year, int):
        info['year'] = year
        if rulebook.min_year and year < rulebook.min_year:
            rule_violations.append(f"Year {year} (min {rulebook.min_year}) (ui/ui_car.json:year)")

    # Tags/body type
    tags = ui.get('tags') if isinstance(ui, dict) else None
    if rulebook.enforce_body_types and isinstance(tags, list):
        tset = {str(t).lower() for t in tags}
        if rulebook.forbid_types and any(ft in tset for ft in rulebook.forbid_types):
            rule_violations.append(f"Forbidden body type tag in {tset} (ui/ui_car.json:tags)")
        if rulebook.allowed_body_types and not any(bt in tset for bt in rulebook.allowed_body_types):
            rule_violations.append(f"Missing allowed body type tag among {rulebook.allowed_body_types} (ui/ui_car.json:tags)")

    # Physics: drivetrain RWD
    ini_duplicate_sections: list[tuple[Path, str]] = []

    def load_ini(path: Path) -> configparser.ConfigParser:
        parser = read_ini(path)
        warnings = getattr(parser, '_warnings', [])
        for warn in warnings:
            if isinstance(warn, str) and warn.lower().startswith('duplicate section:'):
                section = warn.split(':', 1)[1].strip()
            else:
                section = str(warn)
            ini_duplicate_sections.append((path, section))
        return parser

    drv = load_ini(submitted_car_root / 'data' / 'drivetrain.ini')
    dtype_raw = get_str(drv, 'TRACTION', 'TYPE') or ''
    dtype = dtype_raw.split(';', 1)[0].strip()
    info['drivetrain'] = dtype
    if rulebook.enforce_rwd and (dtype or '').upper() != 'RWD':
        rule_violations.append(f"Drivetrain TYPE={dtype} (expected RWD) (data/drivetrain.ini:TRACTION)")

    # Total mass
    car_ini = load_ini(submitted_car_root / 'data' / 'car.ini')
    screen_name = _normalize_name(get_str(car_ini, 'INFO', 'SCREEN_NAME'))
    if screen_name:
        info['car_ini_screen_name'] = screen_name
        screen_valid = _has_prefix(screen_name, expected_prefix)
        info['car_ini_screen_name_valid'] = screen_valid
        if not screen_valid:
            rule_violations.append(f"data/car.ini SCREEN_NAME '{screen_name}' must begin with '{expected_prefix_display}'")
    else:
        info['car_ini_screen_name_valid'] = None
    total_mass = get_float(car_ini, 'BASIC', 'TOTALMASS')
    info['total_mass'] = total_mass
    # Steering related (from car.ini controls)
    steer_lock = get_float(car_ini, 'CONTROLS', 'STEER_LOCK')
    steer_ratio = get_float(car_ini, 'CONTROLS', 'STEER_RATIO')
    lsr_ratio = get_float(car_ini, 'CONTROLS', 'LINEAR_STEER_ROD_RATIO')
    if steer_lock is not None:
        info['steer_lock'] = steer_lock
    if steer_ratio is not None:
        info['steer_ratio'] = steer_ratio
    if lsr_ratio is not None:
        info['linear_steer_rod_ratio'] = lsr_ratio
    # Derived wheel angle approx from data (lower-bound approximation)
    if steer_lock is not None and steer_ratio is not None and steer_ratio > 0:
        derived_angle = steer_lock / steer_ratio
        info['derived_wheel_angle_deg'] = round(derived_angle, 2)
    if rulebook.min_total_mass_kg is not None and (total_mass or 0) < rulebook.min_total_mass_kg:
        rule_violations.append(f"TOTALMASS {total_mass} kg (min {rulebook.min_total_mass_kg} kg) (data/car.ini:BASIC)")

    # Fuel tank location heuristics (ensure competition-safe placement)
    fuel_pos = get_tuple_of_floats(car_ini, 'FUELTANK', 'POSITION')
    info['fuel_tank_pos'] = fuel_pos
    info['fuel_tank_flags'] = []
    info['fuel_tank_distance_to_front_axle'] = None
    info['fuel_tank_distance_to_rear_axle'] = None
    if fuel_pos is not None:
        x, y, z = fuel_pos
        if abs(x) > 0.35:
            fuel_flag_messages.append(f"lateral offset {x:+.2f} m from centerline")
        if not (-0.45 <= y <= 0.45):
            fuel_flag_messages.append(f"vertical position {y:+.2f} m outside -0.45 to 0.45 m window")
        if z > -0.5:
            fuel_flag_messages.append(f"forward placement {z:+.2f} m (should sit behind cockpit)")
        if abs(z) < 0.7:
            fuel_flag_messages.append(f"too close to CG/driver zone (|z|={abs(z):.2f} m)")
        if z < -2.6:
            fuel_flag_messages.append(f"very far rear placement {z:+.2f} m from origin")

    spec_compare: Dict[str, Dict[str, Any]] = {}
    info['spec_compare'] = spec_compare

    def _fmt_value(val: float, unit: str, signed: bool = False) -> str:
        if unit == 'kg':
            return f"{val:+.2f} kg" if signed else f"{val:.2f} kg"
        if unit == 'm':
            return f"{val:+.3f} m" if signed else f"{val:.3f} m"
        if unit == 'mm':
            return f"{val:+.0f} mm" if signed else f"{val:.0f} mm"
        if unit == 'deg':
            return f"{val:+.2f}°" if signed else f"{val:.2f}°"
        if unit == 'ratio':
            return f"{val:+.4f}" if signed else f"{val:.4f}"
        return f"{val:+.4f}" if signed else f"{val:.4f}"

    def record_spec(key: str,
                    submitted: Any,
                    reference: Any,
                    label: str,
                    unit: str,
                    tolerance: float) -> None:
        if submitted is None or reference is None:
            return
        try:
            sub_val = float(submitted)
            ref_val = float(reference)
        except Exception:
            return
        delta = sub_val - ref_val
        within = abs(delta) <= tolerance
        entry = {
            'label': label,
            'submitted': sub_val,
            'reference': ref_val,
            'delta': delta,
            'unit': unit,
            'within_tolerance': within,
            'submitted_display': _fmt_value(sub_val, unit, signed=False),
            'reference_display': _fmt_value(ref_val, unit, signed=False),
            'delta_display': _fmt_value(delta, unit, signed=True),
        }
        spec_compare[key] = entry
        if not within:
            rule_violations.append(
                f"{label} differs from reference: {entry['submitted_display']} vs {entry['reference_display']} (Δ {entry['delta_display']})"
            )

    record_spec('total_mass', info.get('total_mass'), info.get('reference_total_mass'), 'Total mass', 'kg', 0.5)
    record_spec('wheelbase', info.get('wheelbase'), info.get('reference_wheelbase'), 'Wheelbase', 'm', 0.001)
    record_spec('front_track', info.get('front_track'), info.get('reference_front_track'), 'Front track', 'm', 0.001)
    record_spec('rear_track', info.get('rear_track'), info.get('reference_rear_track'), 'Rear track', 'm', 0.001)
    record_spec('front_bias', info.get('front_bias'), info.get('reference_front_bias'), 'Front bias (CG_LOCATION)', 'ratio', 0.0005)
    record_spec('steer_lock', info.get('steer_lock'), info.get('reference_steer_lock'), 'STEER_LOCK', 'deg', 0.05)
    record_spec('steer_ratio', info.get('steer_ratio'), info.get('reference_steer_ratio'), 'STEER_RATIO', 'ratio', 0.01)
    derived_angle = info.get('derived_wheel_angle_deg') or info.get('measured_wheel_angle_deg')
    record_spec('steer_angle', derived_angle, info.get('reference_steer_angle_deg'), 'Max wheel angle', 'deg', 0.3)
    fuel_ref = info.get('reference_fuel_tank_pos')
    if isinstance(fuel_pos, (list, tuple)) and isinstance(fuel_ref, (list, tuple)) and len(fuel_pos) >= 3 and len(fuel_ref) >= 3:
        record_spec('fuel_tank_x', fuel_pos[0], fuel_ref[0], 'Fuel tank X position', 'm', 0.01)
        record_spec('fuel_tank_y', fuel_pos[1], fuel_ref[1], 'Fuel tank Y position', 'm', 0.01)
        record_spec('fuel_tank_z', fuel_pos[2], fuel_ref[2], 'Fuel tank Z position', 'm', 0.01)

    # Gearset overview (drift heuristics)
    gear_overall: list[float] = []
    gear_nominal: list[float] = []
    final_ratio = get_float(drv, 'GEARS', 'FINAL') or get_float(drv, 'FINAL', 'RATIO') or get_float(drv, 'FINAL', 'FINAL')
    gear_count = get_int(drv, 'GEARS', 'COUNT') or 0
    if gear_count and final_ratio:
        for idx in range(1, gear_count + 1):
            ratio = get_float(drv, 'GEARS', f'GEAR_{idx}')
            if ratio is None:
                ratio = get_float(drv, 'GEARS', f'GEAR{idx}')
            if ratio is None:
                continue
            gear_nominal.append(float(ratio))
            gear_overall.append(float(ratio) * float(final_ratio))
    if gear_overall:
        info['gear_overall_ratios'] = gear_overall
    if gear_nominal:
        info['gear_nominal_ratios'] = gear_nominal
    if final_ratio is not None:
        info['final_drive_ratio'] = float(final_ratio)
        record_spec('final_drive_ratio', info.get('final_drive_ratio'), info.get('reference_final_drive_ratio'), 'Final drive ratio', 'ratio', 0.003)
    third_ratio = gear_overall[2] if len(gear_overall) >= 3 else None
    fourth_ratio = gear_overall[3] if len(gear_overall) >= 4 else None
    if third_ratio is not None:
        info['third_gear_overall'] = third_ratio
        record_spec('third_gear_overall', third_ratio, info.get('reference_third_gear_overall'), '3rd gear overall ratio', 'ratio', 0.003)
    if fourth_ratio is not None:
        info['fourth_gear_overall'] = fourth_ratio
        record_spec('fourth_gear_overall', fourth_ratio, info.get('reference_fourth_gear_overall'), '4th gear overall ratio', 'ratio', 0.003)
    if third_ratio is not None:
        # Drift guidance: third gear overall should typically land around 2.6-3.4 (suitable for layouts)
        drift_low = 2.4
        drift_high = 3.6
        if third_ratio < drift_low or third_ratio > drift_high:
            info['drift_third_ratio_warn'] = True
        else:
            info['drift_third_ratio_warn'] = False
        info['drift_third_ratio_range'] = (drift_low, drift_high)
    if final_ratio is not None:
        drift_fd_low = 3.4
        drift_fd_high = 4.6
        if final_ratio < drift_fd_low or final_ratio > drift_fd_high:
            info['drift_final_ratio_warn'] = True
        else:
            info['drift_final_ratio_warn'] = False
        info['drift_final_ratio_range'] = (drift_fd_low, drift_fd_high)

    # Tyre constraints (optional rulebook enforcement)
    tyres_ini = load_ini(submitted_car_root / 'data' / 'tyres.ini')
    # Try first found compound REAR/WIDTH and FRONT/WIDTH
    rear_width: Optional[float] = None
    front_width: Optional[float] = None
    front_dx: Optional[float] = None
    rear_dx: Optional[float] = None
    front_dy: Optional[float] = None
    rear_dy: Optional[float] = None
    for sec in tyres_ini.sections():
        sup = sec.upper()
        if sup.startswith('FRONT'):
            if front_width is None:
                fw = get_float(tyres_ini, sec, 'WIDTH')
                if fw:
                    front_width = fw
            if front_dx is None:
                dx = get_float(tyres_ini, sec, 'DX_REF')
                if dx is not None:
                    front_dx = dx
            if front_dy is None:
                dy = get_float(tyres_ini, sec, 'DY_REF')
                if dy is not None:
                    front_dy = dy
        if sup.startswith('REAR'):
            if rear_width is None:
                rw = get_float(tyres_ini, sec, 'WIDTH')
                if rw:
                    rear_width = rw
            if rear_dx is None:
                dx = get_float(tyres_ini, sec, 'DX_REF')
                if dx is not None:
                    rear_dx = dx
            if rear_dy is None:
                dy = get_float(tyres_ini, sec, 'DY_REF')
                if dy is not None:
                    rear_dy = dy
    if front_width is not None:
        info['front_tyre_width_mm'] = int(round(front_width * 1000))
    if rear_width is not None:
        info['rear_tyre_width_mm'] = int(round(rear_width * 1000))
    record_spec('front_tyre_width_mm', info.get('front_tyre_width_mm'), info.get('reference_front_tyre_width_mm'), 'Front tyre width', 'mm', 0.5)
    record_spec('rear_tyre_width_mm', info.get('rear_tyre_width_mm'), info.get('reference_rear_tyre_width_mm'), 'Rear tyre width', 'mm', 0.5)
    if front_dx is not None:
        info['front_tyre_dx_ref'] = front_dx
    if rear_dx is not None:
        info['rear_tyre_dx_ref'] = rear_dx
    if front_dy is not None:
        info['front_tyre_dy_ref'] = front_dy
    if rear_dy is not None:
        info['rear_tyre_dy_ref'] = rear_dy
    if ref_first_compound:
        tol = 1e-4
        ref_dx = ref_first_compound.get('dx_ref')
        ref_dy = ref_first_compound.get('dy_ref')
        if isinstance(ref_dx, (int, float)):
            if front_dx is not None and abs(front_dx - float(ref_dx)) > tol:
                rule_violations.append(f"Front tyre DX_REF {front_dx:.4f} differs from reference {float(ref_dx):.4f} (data/tyres.ini)")
            if rear_dx is not None and abs(rear_dx - float(ref_dx)) > tol:
                rule_violations.append(f"Rear tyre DX_REF {rear_dx:.4f} differs from reference {float(ref_dx):.4f} (data/tyres.ini)")
        if isinstance(ref_dy, (int, float)):
            if front_dy is not None and abs(front_dy - float(ref_dy)) > tol:
                rule_violations.append(f"Front tyre DY_REF {front_dy:.4f} differs from reference {float(ref_dy):.4f} (data/tyres.ini)")
            if rear_dy is not None and abs(rear_dy - float(ref_dy)) > tol:
                rule_violations.append(f"Rear tyre DY_REF {rear_dy:.4f} differs from reference {float(ref_dy):.4f} (data/tyres.ini)")
    if rulebook.enforce_rear_tyre_max_mm is not None and rear_width is not None:
        if rear_width * 1000 > rulebook.enforce_rear_tyre_max_mm + 1e-6:
            rule_violations.append(f"Rear tyre WIDTH {rear_width*1000:.0f}mm (max {rulebook.enforce_rear_tyre_max_mm}mm) (data/tyres.ini)")
    if rulebook.enforce_front_tyre_range_mm and front_width is not None:
        lo, hi = rulebook.enforce_front_tyre_range_mm
        if front_width * 1000 < lo - 1e-6 or front_width * 1000 > hi + 1e-6:
            rule_violations.append(f"Front tyre WIDTH {front_width*1000:.0f}mm (expected {lo}-{hi}mm) (data/tyres.ini)")

    # KN5 size
    kn5_files = list_kn5_files(submitted_car_root)
    info['kn5_files'] = [p.name for p in kn5_files]
    kn5_sizes: Dict[str, float] = {}
    kn5_prefix_targets: List[str] = []
    kn5_prefix_violations: List[str] = []
    for kn5 in kn5_files:
        sz_mb = _bytes_to_mb(kn5.stat().st_size)
        kn5_sizes[kn5.name] = sz_mb
        if rulebook.max_kn5_mb and sz_mb > rulebook.max_kn5_mb:
            rule_violations.append(f"KN5 file {kn5.name} size {sz_mb:.1f}MB (max {rulebook.max_kn5_mb}MB)")
        stem_lower = kn5.stem.lower()
        if stem_lower in {'collider', 'driver'}:
            continue
        kn5_prefix_targets.append(kn5.name)
        if not _has_prefix(kn5.stem, expected_prefix):
            kn5_prefix_violations.append(kn5.name)
    info['kn5_sizes'] = kn5_sizes
    info['kn5_checked'] = kn5_prefix_targets
    if kn5_prefix_violations:
        info['kn5_prefix_valid'] = False
        info['kn5_prefix_violations'] = kn5_prefix_violations
        short_list = ', '.join(kn5_prefix_violations[:5])
        more = '' if len(kn5_prefix_violations) <= 5 else f", ... (+{len(kn5_prefix_violations)-5} more)"
        rule_violations.append(f"KN5 filenames must begin with '{expected_prefix_display}' (excluding collider/driver): {short_list}{more}")
    else:
        info['kn5_prefix_valid'] = True if kn5_prefix_targets else None

    # Skin size
    skins_dir = submitted_car_root / 'skins'
    if skins_dir.exists():
        # Evaluate largest skin folder
        max_skin_mb = 0.0
        max_skin_name = None
        skins_count = 0
        skins_list: list[str] = []
        textures_info: list[dict] = []
        skins_sizes = {}
        unchecked_textures: List[str] = []
        for skin in skins_dir.iterdir():
            if skin.is_dir():
                skins_count += 1
                skins_list.append(skin.name)
                sz_mb = _bytes_to_mb(folder_size_bytes(skin))
                skins_sizes[skin.name] = sz_mb
                if sz_mb > max_skin_mb:
                    max_skin_mb = sz_mb
                    max_skin_name = skin.name
                # Texture audit (PNG and JPG)
                for tex in skin.rglob('*'):
                    lower = tex.suffix.lower()
                    if lower not in ('.png', '.jpg', '.jpeg'):
                        if lower in ('.dds', '.tga'):
                            try:
                                unchecked_textures.append(str(tex.relative_to(skins_dir.parent)))
                            except Exception:
                                unchecked_textures.append(str(tex))
                        continue
                    try:
                        w = h = 0
                        size_mb = tex.stat().st_size / (1024*1024)
                        if lower == '.png':
                            with tex.open('rb') as f:
                                sig = f.read(8)
                                if sig == b'\x89PNG\r\n\x1a\n':
                                    _ = f.read(8)
                                    hdr = f.read(13)
                                    if len(hdr) == 13:
                                        w = int.from_bytes(hdr[0:4], 'big')
                                        h = int.from_bytes(hdr[4:8], 'big')
                        else:
                            # JPEG parser: scan for SOF0/2 markers to get dimensions
                            with tex.open('rb') as f:
                                data = f.read()
                                i = 0
                                if data[:2] == b'\xff\xd8':
                                    i = 2
                                    while i < len(data):
                                        if data[i] != 0xFF:
                                            i += 1
                                            continue
                                        marker = data[i+1]
                                        i += 2
                                        if marker in (0xC0, 0xC2):  # SOF0, SOF2
                                            length = int.from_bytes(data[i:i+2], 'big')
                                            if i+5 < len(data):
                                                # skip precision byte
                                                h = int.from_bytes(data[i+3:i+5], 'big')
                                                w = int.from_bytes(data[i+5:i+7], 'big')
                                            break
                                        else:
                                            length = int.from_bytes(data[i:i+2], 'big') if i+2 <= len(data) else 0
                                            i += length
                        textures_info.append({'file': str(tex.relative_to(skins_dir.parent)), 'w': w, 'h': h, 'size_mb': size_mb})
                        if w and h and (w > 4096 or h > 4096):
                            rule_violations.append(f"Large texture dimensions {w}x{h} in {tex.name} (>4096)")
                    except Exception:
                        pass
        info['max_skin'] = {'name': max_skin_name, 'size_mb': max_skin_mb}
        if rulebook.max_skin_mb and max_skin_mb > rulebook.max_skin_mb:
            rule_violations.append(f"Largest skin '{max_skin_name}' is {max_skin_mb:.1f}MB (max {rulebook.max_skin_mb}MB)")
        info['skins_count'] = skins_count
        info['skins'] = skins_list
        info['skins_sizes'] = skins_sizes
        info['textures'] = textures_info
        if unchecked_textures:
            info['textures_unchecked'] = unchecked_textures
        if skins_count != 1:
            rule_violations.append(f"Skins count {skins_count} (expected 1)")

    # Data files whitelist vs reference
    ref_path: Optional[Path] = None
    ref_setup_ini: Optional[configparser.ConfigParser] = None
    ref_root_dirs: set[str] = set()
    ref_root_files: set[str] = set()
    try:
        if cmp.matched_key:
            ref_entry = reference_index.get(cmp.matched_key)
            if isinstance(ref_entry, dict):
                ref_path = Path(ref_entry.get('path', ''))
                ref_data = (ref_path / 'data') if ref_path.exists() else None
                sub_data = submitted_car_root / 'data'
                ref_total_mass = ref_entry.get('total_mass')
                if isinstance(ref_total_mass, (int, float)):
                    info['reference_total_mass'] = ref_total_mass
                ref_fb = ref_entry.get('cg_location')
                if isinstance(ref_fb, (int, float)):
                    info['reference_front_bias'] = ref_fb
                ref_ft = ref_entry.get('front_track')
                if isinstance(ref_ft, (int, float)):
                    info['reference_front_track'] = ref_ft
                ref_rt = ref_entry.get('rear_track')
                if isinstance(ref_rt, (int, float)):
                    info['reference_rear_track'] = ref_rt
                ref_wb = ref_entry.get('wheelbase')
                if isinstance(ref_wb, (int, float)):
                    info['reference_wheelbase'] = ref_wb
                ref_fuel = ref_entry.get('fuel_tank_pos')
                if isinstance(ref_fuel, (list, tuple)):
                    info['reference_fuel_tank_pos'] = tuple(ref_fuel)
                compounds = ref_entry.get('tyre_compounds') or []
                if isinstance(compounds, list) and compounds:
                    comp0 = compounds[0]
                    if isinstance(comp0, dict):
                        ref_first_compound = comp0
                        wf = comp0.get('width_front')
                        wr = comp0.get('width_rear')
                        if isinstance(wf, (int, float)):
                            info['reference_front_tyre_width_mm'] = int(round(wf * 1000))
                        if isinstance(wr, (int, float)):
                            info['reference_rear_tyre_width_mm'] = int(round(wr * 1000))
                ref_steer_lock = ref_entry.get('steer_lock')
                ref_steer_ratio = ref_entry.get('steer_ratio')
                ref_steer_angle = ref_entry.get('steer_max_wheel_deg')
                ref_drivetrain = ref_entry.get('drivetrain_type')
                if ref_drivetrain:
                    info['reference_drivetrain'] = ref_drivetrain
                    if dtype and str(dtype).strip().upper() != str(ref_drivetrain).strip().upper():
                        rule_violations.append(
                            f"Drivetrain TYPE differs from reference: {dtype} vs {ref_drivetrain}"
                        )
                ref_gears_list = ref_entry.get('gears') if isinstance(ref_entry.get('gears'), list) else None
                ref_final_ratio = ref_entry.get('final_ratio')
                if isinstance(ref_final_ratio, (int, float)):
                    try:
                        info['reference_final_drive_ratio'] = float(ref_final_ratio)
                    except Exception:
                        info['reference_final_drive_ratio'] = ref_final_ratio
                if ref_gears_list and isinstance(ref_final_ratio, (int, float)):
                    try:
                        ref_overall = [abs(float(g)) * abs(float(ref_final_ratio)) for g in ref_gears_list]
                    except Exception:
                        ref_overall = []
                    if ref_overall:
                        info['reference_gear_overall'] = ref_overall
                        if len(ref_overall) >= 3:
                            info['reference_third_gear_overall'] = ref_overall[2]
                        if len(ref_overall) >= 4:
                            info['reference_fourth_gear_overall'] = ref_overall[3]
                if ref_steer_lock is not None:
                    info['reference_steer_lock'] = ref_steer_lock
                if ref_steer_ratio is not None:
                    info['reference_steer_ratio'] = ref_steer_ratio
                if ref_steer_angle is None and ref_steer_lock and ref_steer_ratio:
                    try:
                        ref_steer_angle = float(ref_steer_lock) / float(ref_steer_ratio)
                    except Exception:
                        ref_steer_angle = None
                if ref_steer_angle is not None:
                    try:
                        info['reference_steer_angle_deg'] = round(float(ref_steer_angle), 2)
                    except Exception:
                        info['reference_steer_angle_deg'] = ref_steer_angle
                if ref_data and sub_data.exists():
                    ref_files = {p.name for p in ref_data.iterdir() if p.is_file()}
                    sub_files = {p.name for p in sub_data.iterdir() if p.is_file()}
                    extra = sorted(sub_files - ref_files)
                    missing = sorted(ref_files - sub_files)
                    if extra:
                        for f in extra:
                            rule_violations.append(f"Unexpected file in data: {f}")
                    if missing:
                        for f in missing:
                            rule_violations.append(f"Missing expected data file: {f}")
                    info['data_files_ok'] = not extra and not missing
                    info['data_files_extra'] = extra
                    info['data_files_missing'] = missing
                if ref_path and ref_path.exists():
                    setup_ref_path = ref_path / 'data' / 'setup.ini'
                    if setup_ref_path.exists():
                        try:
                            ref_setup_ini = read_ini(setup_ref_path)
                        except Exception:
                            ref_setup_ini = None
                    try:
                        for entry in ref_path.iterdir():
                            if entry.is_dir():
                                ref_root_dirs.add(entry.name)
                            elif entry.is_file():
                                ref_root_files.add(entry.name)
                    except Exception:
                        ref_root_dirs = set()
                        ref_root_files = set()
                ref_hashes = ref_entry.get('hashed_files') if isinstance(ref_entry.get('hashed_files'), dict) else {}
                data_modifications: List[Dict[str, Any]] = []
                if ref_hashes:
                    hash_mismatches: list[Dict[str, str]] = []
                    for rel, expected_hash in ref_hashes.items():
                        try:
                            rel_path = Path(rel)
                        except Exception:
                            continue
                        sub_path = submitted_car_root / rel_path
                        if not sub_path.exists():
                            continue
                        actual_hash = _sha1_file(sub_path)
                        if actual_hash and actual_hash != expected_hash:
                            rel_norm = rel.replace('\\', '/')
                            lower_rel = rel_norm.lower()
                            hash_mismatches.append({
                                'path': rel_norm,
                                'expected': expected_hash,
                                'actual': actual_hash,
                            })
                            if lower_rel == 'collider.kn5':
                                rule_violations.append("Collider KN5 differs from reference (collider.kn5)")
                                info['collider_hash_mismatch'] = True
                            elif lower_rel.startswith('data/'):
                                ref_file = ref_path / rel_path if ref_path else None
                                analysis = None
                                if ref_file and ref_file.exists() and rel_norm.lower().endswith('.ini'):
                                    analysis = _analyze_ini_delta(sub_path, ref_file)
                                if analysis:
                                    analysis['path'] = rel_norm
                                    data_modifications.append(analysis)
                                    severity = str(analysis.get('severity', 'high'))
                                else:
                                    severity = 'high'
                                    data_modifications.append({
                                        'path': rel_norm,
                                        'severity': severity,
                                        'changes': [{'detail': 'Binary change', 'severity': severity}],
                                    })
                                info['data_files_ok'] = False
                                rule_violations.append(f"Data file changed ({severity}) {rel_norm}")
                            elif lower_rel.startswith('extension/'):
                                info.setdefault('extension_hash_mismatches', []).append(rel_norm)
                    if hash_mismatches:
                        info['hash_mismatches'] = hash_mismatches
                if data_modifications:
                    info['data_modifications'] = data_modifications
                ref_extension_hashes: Dict[str, str] = {}
                if ref_hashes:
                    ref_extension_hashes = {k: v for k, v in ref_hashes.items() if k.startswith('extension/')}
                submitted_extension_dir = submitted_car_root / 'extension'
                extension_summary: Dict[str, Any] = {}
                if submitted_extension_dir.exists():
                    extension_files: List[str] = []
                    cosmetic_files: List[str] = []
                    physics_files: List[str] = []
                    physics_details: List[Dict[str, Any]] = []
                    unknown_files: List[str] = []
                    for p in submitted_extension_dir.rglob('*'):
                        if not p.is_file():
                            continue
                        rel = str(p.relative_to(submitted_car_root)).replace('\\', '/')
                        classification, reason = _classify_extension_entry(rel, p)
                        extension_files.append(rel)
                        if classification == 'physics':
                            physics_files.append(rel)
                            physics_details.append({'file': rel, 'reason': reason})
                        elif classification == 'cosmetic':
                            cosmetic_files.append(rel)
                        else:
                            unknown_files.append(rel)
                    extension_summary['files'] = sorted(extension_files)
                    extension_summary['file_count'] = len(extension_files)
                    extension_summary['cosmetic_count'] = len(cosmetic_files)
                    if cosmetic_files:
                        extension_summary['cosmetic_sample'] = sorted(cosmetic_files)[:20]
                    if physics_files:
                        extension_summary['physics'] = sorted(physics_files)
                        extension_summary['physics_details'] = physics_details[:20]
                    extension_summary['physics_count'] = len(physics_files)
                    if unknown_files:
                        extension_summary['unknown'] = sorted(unknown_files)[:50]
                    extension_summary['unknown_count'] = len(unknown_files)
                    extension_summary['expected'] = bool(ref_extension_hashes)
                    if physics_files:
                        details = []
                        for item in physics_details[:5]:
                            reason = item.get('reason')
                            if reason:
                                details.append(f"{item['file']} ({reason})")
                            else:
                                details.append(item['file'])
                        detail_str = '; '.join(details)
                        rule_violations.append(f"Extension folder contains potential physics overrides: {detail_str}")
                        extension_summary['status'] = 'flagged'
                    elif unknown_files:
                        extension_summary['status'] = 'needs_review'
                    else:
                        extension_summary['status'] = 'cosmetic'
                else:
                    if ref_extension_hashes:
                        rule_violations.append("Expected extension config missing (extension/)")
                        extension_summary = {
                            'status': 'missing',
                            'expected': True,
                            'files': [],
                            'file_count': 0,
                            'cosmetic_count': 0,
                            'unknown_count': 0,
                        }
                if extension_summary:
                    info['extension_summary'] = extension_summary
    except Exception:
        pass

    # Root-level inventory
    SUSPICIOUS_ROOT_DIRS = {'apps', 'python', 'python27', 'scripts', 'tools', 'acstuff', 'content', 'system', 'server', 'mods', 'bin'}
    SUSPICIOUS_ROOT_FILE_EXTS = {'.bat', '.ps1', '.cmd', '.exe', '.dll', '.vbs', '.sh', '.lua', '.py', '.jar'}
    try:
        sub_root_dirs = sorted([p.name for p in submitted_car_root.iterdir() if p.is_dir()])
        sub_root_files = sorted([p.name for p in submitted_car_root.iterdir() if p.is_file()])
        info['root_directories'] = sub_root_dirs
        info['root_files'] = sub_root_files
        suspicious_dirs = [d for d in sub_root_dirs if d.lower() in SUSPICIOUS_ROOT_DIRS]
        suspicious_files = [f for f in sub_root_files if Path(f).suffix.lower() in SUSPICIOUS_ROOT_FILE_EXTS]
        if suspicious_dirs:
            info['root_suspicious_dirs'] = suspicious_dirs
            rule_violations.append(f"Suspicious root directories: {', '.join(suspicious_dirs)}")
        if suspicious_files:
            info['root_suspicious_files'] = suspicious_files
            rule_violations.append(f"Suspicious root files: {', '.join(suspicious_files)}")
        if ref_root_dirs:
            SAFE_EXTRA_ROOT_DIRS = {'analysis', 'telemetry', 'media', 'logs', 'screenshots'}
            SAFE_MISSING_ROOT_DIRS = {'extension'}
            extra_dirs = sorted(set(sub_root_dirs) - ref_root_dirs)
            missing_dirs = sorted(ref_root_dirs - set(sub_root_dirs))
            ignored_extra_dirs = [d for d in extra_dirs if d.lower() in SAFE_EXTRA_ROOT_DIRS]
            ignored_missing_dirs = [d for d in missing_dirs if d.lower() in SAFE_MISSING_ROOT_DIRS]
            extra_dirs = [d for d in extra_dirs if d not in ignored_extra_dirs]
            missing_dirs = [d for d in missing_dirs if d not in ignored_missing_dirs]
            if ignored_extra_dirs:
                info['root_extra_dirs_ignored'] = ignored_extra_dirs
            if ignored_missing_dirs:
                info['root_missing_dirs_ignored'] = ignored_missing_dirs
            if extra_dirs:
                info['root_extra_dirs'] = extra_dirs
                rule_violations.append(f"Unexpected root directories: {', '.join(extra_dirs[:10])}")
            if missing_dirs:
                info['root_missing_dirs'] = missing_dirs
                rule_violations.append(f"Missing root directories vs reference: {', '.join(missing_dirs[:10])}")
        if ref_root_files:
            SAFE_ROOT_FILE_EXTS = {'.kn5'}
            extra_files = sorted(set(sub_root_files) - ref_root_files)
            missing_files = sorted(ref_root_files - set(sub_root_files))
            ignored_extra_files = [f for f in extra_files if Path(f).suffix.lower() in SAFE_ROOT_FILE_EXTS]
            ignored_missing_files = [f for f in missing_files if Path(f).suffix.lower() in SAFE_ROOT_FILE_EXTS]
            extra_files = [f for f in extra_files if f not in ignored_extra_files]
            missing_files = [f for f in missing_files if f not in ignored_missing_files]
            if ignored_extra_files:
                info['root_extra_files_ignored'] = ignored_extra_files
            if ignored_missing_files:
                info['root_missing_files_ignored'] = ignored_missing_files
            if extra_files:
                info['root_extra_files'] = extra_files
                rule_violations.append(f"Unexpected root files: {', '.join(extra_files[:10])}")
            if missing_files:
                info['root_missing_files'] = missing_files
                rule_violations.append(f"Missing root files vs reference: {', '.join(missing_files[:10])}")
    except Exception:
        pass

    # Colliders heuristics vs body extents
    susp = load_ini(submitted_car_root / 'data' / 'suspensions.ini')
    wheelbase = get_float(susp, 'BASIC', 'WHEELBASE') or get_float(susp, 'FRONT', 'WHEELBASE')
    ftrack = get_float(susp, 'FRONT', 'TRACK')
    rtrack = get_float(susp, 'REAR', 'TRACK')
    toe_out_front = get_float(susp, 'FRONT', 'TOE_OUT')
    cg_location = get_float(susp, 'BASIC', 'CG_LOCATION')
    info['wheelbase'] = wheelbase
    info['front_track'] = ftrack
    info['rear_track'] = rtrack
    if toe_out_front is not None:
        info['front_toe_out'] = toe_out_front
    if cg_location is not None:
        info['front_bias'] = cg_location
        if rulebook.enforce_front_bias is not None:
            # Allow minor tolerance of 0.005 (0.5%)
            if abs(cg_location - rulebook.enforce_front_bias) > 0.005:
                rule_violations.append(
                    f"Front bias CG_LOCATION={cg_location:.3f} expected {rulebook.enforce_front_bias:.3f} (data/suspensions.ini:BASIC)"
                )
    if fuel_pos is not None and wheelbase and cg_location is not None:
        try:
            front_axle_z = float(wheelbase) * float(cg_location)
            rear_axle_z = -float(wheelbase) * (1.0 - float(cg_location))
            dist_front = abs(fuel_pos[2] - front_axle_z)
            dist_rear = abs(fuel_pos[2] - rear_axle_z)
            info['fuel_tank_distance_to_front_axle'] = dist_front
            info['fuel_tank_distance_to_rear_axle'] = dist_rear
            axle_clearance = 0.04  # 40 mm clearance around axle planes
            if dist_front < axle_clearance or dist_rear < axle_clearance:
                fuel_flag_messages.append(
                    f"too close to axle plane (front Δ={dist_front:.2f} m, rear Δ={dist_rear:.2f} m)"
                )
        except Exception:
            pass
    coll_path = submitted_car_root / 'data' / 'colliders.ini'
    if coll_path.exists():
        coll = load_ini(coll_path)
        for sec in coll.sections():
            if not sec.startswith('COLLIDER_'):
                continue
            centre = get_tuple_of_floats(coll, sec, 'CENTRE')
            size = get_tuple_of_floats(coll, sec, 'SIZE')
            if not (centre and size):
                continue
            sx, sy, sz = size
            # width vs track heuristic: must not exceed max(front,rear)+0.2
            if ftrack and rtrack and sx > max(ftrack, rtrack) + 0.2:
                rule_violations.append(
                    f"Collider {sec} width {sx:.3f} > track+0.2 (max {max(ftrack,rtrack)+0.2:.3f}) (data/colliders.ini)"
                )
            # length vs wheelbase heuristic: must not exceed wheelbase + 0.8
            if wheelbase and sz > wheelbase + 0.8:
                rule_violations.append(
                    f"Collider {sec} length {sz:.3f} > wheelbase+0.8 (max {wheelbase+0.8:.3f}) (data/colliders.ini)"
                )

    # Setup locked ranges (min==max) & range comparison
    setup_path = submitted_car_root / 'data' / 'setup.ini'
    setup_locked = []
    toe_zero_ok: Optional[bool] = None
    toe_ranges: Dict[str, tuple[float, float]] = {}
    setup_range_issues: List[str] = []
    try:
        if setup_path.exists():
            sup = load_ini(setup_path)
            ref_sections_lookup: Dict[str, str] = {}
            if ref_setup_ini:
                ref_sections_lookup = {sec.lower(): sec for sec in ref_setup_ini.sections()}
            seen_sections: set[str] = set()
            for sec in sup.sections():
                sec_lower = sec.lower()
                seen_sections.add(sec_lower)
                ref_sec = ref_sections_lookup.get(sec_lower) if ref_setup_ini else None
                if ref_setup_ini and ref_sec is None:
                    msg = f"Unexpected setup section vs reference: [{sec}]"
                    rule_violations.append(msg)
                    setup_range_issues.append(msg)
                s = sup[sec]
                if 'MIN' in s and 'MAX' in s:
                    try:
                        vmin = float(str(s['MIN']).replace(',', '.'))
                        vmax = float(str(s['MAX']).replace(',', '.'))
                        if abs(vmin - vmax) < 1e-9:
                            setup_locked.append(sec)
                        name = sec.upper()
                        if name in ('TOE_OUT_LF', 'TOE_OUT_RF', 'TOE_OUT_LR', 'TOE_OUT_RR'):
                            toe_ranges[name] = (vmin, vmax)
                    except Exception:
                        pass
                if ref_setup_ini and ref_sec:
                    ref_min = get_float(ref_setup_ini, ref_sec, 'MIN')
                    ref_max = get_float(ref_setup_ini, ref_sec, 'MAX')
                    sub_min = get_float(sup, sec, 'MIN')
                    sub_max = get_float(sup, sec, 'MAX')
                    tol = 1e-6
                    if ref_min is not None and sub_min is not None and sub_min < ref_min - tol:
                        msg = f"Setup [{sec}] MIN {sub_min} < reference {ref_min}"
                        rule_violations.append(msg)
                        setup_range_issues.append(msg)
                    if ref_max is not None and sub_max is not None and sub_max > ref_max + tol:
                        msg = f"Setup [{sec}] MAX {sub_max} > reference {ref_max}"
                        rule_violations.append(msg)
                        setup_range_issues.append(msg)
            if ref_setup_ini:
                missing_sections = sorted(set(ref_sections_lookup) - seen_sections)
                if missing_sections:
                    names = ', '.join(ref_sections_lookup[m] for m in missing_sections[:10])
                    msg = f"Setup missing sections vs reference: {names}"
                    rule_violations.append(msg)
                    setup_range_issues.append(msg)
            # Determine if zero toe is reachable on front
            def has_zero(rng: Optional[tuple[float, float]]):
                if not rng:
                    return None
                vmin, vmax = rng
                lo, hi = (min(vmin, vmax), max(vmin, vmax))
                return (lo - 1e-9) <= 0.0 <= (hi + 1e-9)
            lf = toe_ranges.get('TOE_OUT_LF')
            rf = toe_ranges.get('TOE_OUT_RF')
            z_l = has_zero(lf)
            z_r = has_zero(rf)
            if z_l is not None and z_r is not None:
                toe_zero_ok = bool(z_l and z_r)
            elif z_l is not None:
                toe_zero_ok = bool(z_l)
            elif z_r is not None:
                toe_zero_ok = bool(z_r)
    except Exception:
        pass
    if setup_locked:
        info['setup_locked'] = setup_locked
    if toe_zero_ok is not None:
        info['setup_toe_zero_ok'] = toe_zero_ok
    if toe_ranges:
        info['setup_toe_ranges'] = {k: {'min': v[0], 'max': v[1]} for k, v in toe_ranges.items()}
    if setup_range_issues:
        info['setup_range_issues'] = setup_range_issues
    if fuel_pos is not None:
        # Deduplicate messages while preserving order
        seen_flags: set[str] = set()
        ordered_flags: List[str] = []
        for flag in fuel_flag_messages:
            if flag not in seen_flags:
                ordered_flags.append(flag)
                seen_flags.add(flag)
        info['fuel_tank_flags'] = ordered_flags
        if ordered_flags:
            issues = '; '.join(ordered_flags)
            rule_violations.append(
                f"Fuel tank POSITION={fuel_pos} flagged: {issues} (data/car.ini:FUELTANK)"
            )
    else:
        info['fuel_tank_flags'] = []

    # Power curve info
    power_lut = submitted_car_root / 'data' / 'power.lut'
    if power_lut.exists():
        curve = read_lut(power_lut)
        rpm_pk, p_pk = peak_values(curve)
        info['power_peak'] = {'rpm': rpm_pk, 'power': p_pk}
        # Prepare power and torque graphs
        rpms = [x for x, _ in curve]
        powers_hp = [y for _, y in curve]
        import math
        torques = []
        for (x, y) in curve:
            rpm = x if x > 0 else 1.0
            hp = y
            w = hp * 745.699872
            t_nm = w / (2 * math.pi * (rpm / 60.0))
            torques.append(t_nm)
        info['power_curve'] = {
            'unit': 'hp',
            'max': max(powers_hp) if powers_hp else 0,
            'spark': sparkline(powers_hp, length=60),
        }
        info['torque_curve'] = {
            'unit': 'Nm',
            'max': max(torques) if torques else 0,
            'spark': sparkline(torques, length=60),
        }
        def _interp(points: list[tuple[float, float]], rpm_target: float) -> float:
            if not points:
                return 0.0
            for idx in range(1, len(points)):
                r0, v0 = points[idx - 1]
                r1, v1 = points[idx]
                if r0 <= rpm_target <= r1:
                    span = r1 - r0
                    if span <= 1e-6:
                        return v0
                    t = (rpm_target - r0) / span
                    return v0 + t * (v1 - v0)
            if rpm_target < points[0][0]:
                return points[0][1]
            return points[-1][1]
        try:
            def _hp_to_torque(hp_val: float, rpm_val: float) -> float:
                if rpm_val <= 0 or hp_val <= 0:
                    return 0.0
                watts = hp_val * 745.699872
                return watts / (2 * math.pi * (rpm_val / 60.0))
            torque_4000 = _hp_to_torque(_interp(curve, 4000.0), 4000.0)
            torque_5500 = _hp_to_torque(_interp(curve, 5500.0), 5500.0)
            hp_6500 = _interp(curve, 6500.0)
            info['torque_at_4000'] = torque_4000
            info['torque_at_5500'] = torque_5500
            info['hp_at_6500'] = hp_6500
            info['drift_torque_targets'] = {'rpm': [4000, 5500], 'torque': [500.0, 450.0], 'hp_6500': 600.0}
            info['drift_torque_warn'] = torque_4000 < 500.0 or torque_5500 < 450.0 or hp_6500 < 550.0
        except Exception:
            pass
    # Content Manager steering measurement (optional)
    cm_dir = submitted_car_root / 'analysis'
    cm_steer = cm_dir / 'cm_steer.json'
    # Auto-generate CM steer file if configured and missing
    if not cm_steer.exists() and rulebook.cm_steer_cmd:
        try:
            import subprocess
            cm_dir.mkdir(parents=True, exist_ok=True)
            cmd = rulebook.cm_steer_cmd.format(car=str(submitted_car_root), out=str(cm_steer))
            import subprocess as _sp
            _sp.run(cmd, shell=True, check=False, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass
    if cm_steer.exists():
        try:
            import json
            data = json.loads(cm_steer.read_text(encoding='utf-8', errors='ignore'))
            max_angle = None
            if isinstance(data, dict):
                if 'max_wheel_angle_deg' in data:
                    try:
                        max_angle = abs(float(data['max_wheel_angle_deg']))
                    except Exception:
                        pass
                elif 'left_max_deg' in data and 'right_max_deg' in data:
                    try:
                        max_angle = max(abs(float(data['left_max_deg'])), abs(float(data['right_max_deg'])))
                    except Exception:
                        pass
            # If the CM script returned STEER_LOCK instead of wheel angle, correct it using car.ini
            try:
                steer_lock_val = info.get('steer_lock')
                steer_ratio_val = info.get('steer_ratio')
                if max_angle is not None and steer_lock_val and steer_ratio_val:
                    # Expected per-side wheel angle approximation in AC: STEER_LOCK / STEER_RATIO
                    expected = abs((steer_lock_val) / steer_ratio_val) if steer_ratio_val else None
                    if expected is not None:
                        looks_like_lock = max_angle > 90.0 or abs(max_angle - steer_lock_val) < 5.0
                        too_large_vs_expected = max_angle > expected * 1.5
                        too_small_vs_expected = max_angle < expected * 0.75
                        if looks_like_lock or too_large_vs_expected:
                            max_angle = round(expected, 2)
                            if isinstance(data, dict):
                                data['max_wheel_angle_deg'] = max_angle
                                data.setdefault('source', 'normalized')
                                data['note'] = 'value normalized from STEER_LOCK/STEER_RATIO'
                        elif too_small_vs_expected:
                            max_angle = round(expected, 2)
                            if isinstance(data, dict):
                                data['max_wheel_angle_deg'] = max_angle
                                data.setdefault('source', 'normalized_low')
                                data['note'] = 'CM reading appeared low; normalized using STEER_LOCK/STEER_RATIO'
            except Exception:
                pass
            # Normalize stored value to positive and rounded for display/reporting
            if isinstance(data, dict) and max_angle is not None:
                data['max_wheel_angle_deg'] = round(abs(max_angle), 2)
            # Unified measured angle + source for report
            if max_angle is not None:
                info['measured_wheel_angle_deg'] = round(abs(max_angle), 2)
                src = (data.get('source') if isinstance(data, dict) else None) or 'CM'
                info['steer_source'] = str(src)
            # Attach (possibly normalized) CM steering payload
            info['cm_steer'] = data
            if rulebook.max_steer_angle_deg is not None and max_angle is not None:
                if max_angle > rulebook.max_steer_angle_deg + 1e-6:
                    rule_violations.append(
                        f"Measured max wheel angle {max_angle:.1f}° (max {rulebook.max_steer_angle_deg:.1f}°) (analysis/cm_steer.json at 0 toe)"
                    )
        except Exception:
            rule_violations.append("Failed to parse analysis/cm_steer.json")
    elif rulebook.require_cm_steer_file and rulebook.max_steer_angle_deg is not None:
        # Fallback: derive from car.ini when command not available
        try:
            car_ini = load_ini(submitted_car_root / 'data' / 'car.ini')
            steer_lock = get_float(car_ini, 'CONTROLS', 'STEER_LOCK') or 0.0
            steer_ratio = get_float(car_ini, 'CONTROLS', 'STEER_RATIO') or 0.0
            # In Assetto Corsa, STEER_LOCK is from center to one side (not lock-to-lock).
            # Approximate per-side wheel angle at max input is STEER_LOCK / STEER_RATIO.
            derived = round(abs(((steer_lock) / steer_ratio) if steer_ratio else 0.0), 2)
            import json
            cm_dir.mkdir(parents=True, exist_ok=True)
            cm_steer.write_text(json.dumps({'max_wheel_angle_deg': derived, 'source': 'derived'}), encoding='utf-8')
            # Accept derived value as measurement
            info['cm_steer'] = {'max_wheel_angle_deg': derived, 'source': 'derived'}
            info['measured_wheel_angle_deg'] = derived
            info['steer_source'] = 'derived'
            if derived > rulebook.max_steer_angle_deg + 1e-6:
                rule_violations.append(
                    f"Measured max wheel angle {derived:.1f}° (max {rulebook.max_steer_angle_deg:.1f}°) (derived from car.ini)"
                )
        except Exception:
            rule_violations.append(f"Missing analysis/cm_steer.json for steering validation (required, max {rulebook.max_steer_angle_deg:.1f}°)")

    # Simulated steering angles using simple Ackermann approximation at 0 toe
    try:
        # Only compute if we have the inputs
        car_ini = load_ini(submitted_car_root / 'data' / 'car.ini')
        steer_lock = get_float(car_ini, 'CONTROLS', 'STEER_LOCK') or 0.0
        steer_ratio = get_float(car_ini, 'CONTROLS', 'STEER_RATIO') or 0.0
        base_deg = (steer_lock / steer_ratio) if steer_ratio else None
        if base_deg and ftrack and wheelbase:
            import math
            base = math.radians(base_deg)
            # Scenario A: treat base as outer angle
            innerA = outerA = None
            try:
                R1 = (wheelbase / math.tan(base)) - (ftrack / 2.0)
                if R1 > (ftrack / 2.0):
                    innerA = math.degrees(math.atan(wheelbase / (R1 - ftrack / 2.0)))
                    outerA = base_deg
            except Exception:
                innerA = outerA = None
            # Scenario B: treat base as inner angle
            innerB = outerB = None
            try:
                R2 = (wheelbase / math.tan(base)) + (ftrack / 2.0)
                if R2 > 0:
                    outerB = math.degrees(math.atan(wheelbase / (R2 + ftrack / 2.0)))
                    innerB = base_deg
            except Exception:
                innerB = outerB = None
            # Prefer scenario B (usually inner > outer). Fallback to A if invalid.
            if innerB and outerB:
                inner, outer = innerB, outerB
                src = 'simulated_ackermann_inner'
            elif innerA and outerA:
                inner, outer = innerA, outerA
                src = 'simulated_ackermann_outer'
            else:
                inner = outer = base_deg
                src = 'simulated_from_ini'
            info['sim_steer'] = {
                'left_max_deg': round(abs(inner), 2),
                'right_max_deg': round(abs(inner), 2),
                'inner_deg': round(abs(inner), 2),
                'outer_deg': round(abs(outer), 2),
                'source': src,
                'toe_baseline_m': info.get('front_toe_out'),
            }
    except Exception:
        pass

    # Provide a geometry-based simulated steering angle if CM data is absent (improved)
    try:
        if 'measured_wheel_angle_deg' not in info and 'sim_steer' not in info:
            from .steering_solver import solve_true_steer_angles
            solved = solve_true_steer_angles(submitted_car_root)
            if solved:
                info['sim_steer'] = {
                    'left_max_deg': solved[0],
                    'right_max_deg': solved[1],
                    'inner_deg': solved[0],
                    'outer_deg': solved[1],
                    'source': 'simulated_geometry',
                    'toe_baseline_m': info.get('front_toe_out'),
                }
    except Exception:
        pass

    if 'measured_wheel_angle_deg' not in info and info.get('derived_wheel_angle_deg') is not None:
        info['measured_wheel_angle_deg'] = info['derived_wheel_angle_deg']
        info.setdefault('steer_source', 'derived_ratio')

    try:
        ref_angle = info.get('reference_steer_angle_deg')
        measured_angle = info.get('measured_wheel_angle_deg') or info.get('derived_wheel_angle_deg')
        if ref_angle is not None and measured_angle is not None:
            diff = float(measured_angle) - float(ref_angle)
            info['steer_reference_delta'] = round(diff, 2)
            info['steer_reference_within_tol'] = abs(diff) <= 0.5
    except Exception:
        pass

    # KN5 stats integration (optional)
    kn5_stats = cm_dir / 'kn5_stats.json'
    # Auto-generate KN5 stats if configured and missing
    if not kn5_stats.exists() and rulebook.ks_stats_cmd:
        try:
            import subprocess
            cm_dir.mkdir(parents=True, exist_ok=True)
            cmd = rulebook.ks_stats_cmd.format(car=str(submitted_car_root), out=str(kn5_stats))
            import subprocess as _sp
            _sp.run(cmd, shell=True, check=False, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass
    if kn5_stats.exists():
        try:
            import json
            data = json.loads(kn5_stats.read_text(encoding='utf-8', errors='ignore'))
            info['kn5_stats'] = data
            total_tris = None
            total_objs = None
            if isinstance(data, dict):
                total_tris = data.get('total_triangles')
                total_objs = data.get('total_objects')
                if total_tris is None and 'files' in data and isinstance(data['files'], list):
                    t = 0
                    o = 0
                    for f in data['files']:
                        try:
                            t += int(f.get('triangles', 0))
                            o += int(f.get('objects', 0))
                        except Exception:
                            pass
                    total_tris = t
                    total_objs = o
            if rulebook.max_triangles is not None and isinstance(total_tris, int):
                if total_tris > rulebook.max_triangles:
                    rule_violations.append(
                        f"Total triangles {total_tris} (max {rulebook.max_triangles}) (analysis/kn5_stats.json)"
                    )
            if rulebook.max_objects is not None and isinstance(total_objs, int):
                if total_objs > rulebook.max_objects:
                    rule_violations.append(
                        f"Total objects {total_objs} (max {rulebook.max_objects}) (analysis/kn5_stats.json)"
                    )
        except Exception:
            rule_violations.append("Failed to parse analysis/kn5_stats.json")
    elif rulebook.require_kn5_stats_file:
        # Fallback: estimate from UI LODs if available
        try:
            import json
            ui = submitted_car_root / 'ui' / 'cm_lods_generation.json'
            total_tris = None
            if ui.exists():
                try:
                    raw = json.loads(ui.read_text(encoding='utf-8', errors='ignore'))
                    stages = raw.get('Stages', {})
                    tris = 0
                    for k, v in stages.items():
                        if isinstance(v, str):
                            v = json.loads(v)
                        tris += int(v.get('trianglesCount', 0))
                    total_tris = tris
                except Exception:
                    pass
            info['kn5_stats'] = {'total_triangles': total_tris, 'total_objects': None, 'source': 'ui_lods'}
            if rulebook.max_triangles is not None and isinstance(total_tris, int) and total_tris > rulebook.max_triangles:
                rule_violations.append(
                    f"Total triangles {total_tris} (max {rulebook.max_triangles}) (ui estimate)"
                )
        except Exception:
            rule_violations.append("Missing analysis/kn5_stats.json for model validation (required)")

    # Fallback reference for exact physics (e.g., E92)
    if not cmp.exact_match and rulebook.fallback_reference_key:
        from .matcher import exact_compare_pair
        fb_key = rulebook.fallback_reference_key
        ref_fp = fingerprint_index.get(fb_key)
        if ref_fp:
            exact_fb, fb_mismatches, _, _ = exact_compare_pair(submitted_fp, ref_fp)
            if exact_fb:
                info['fallback_used'] = True
                info['fallback_reference'] = fb_key
                return ValidationResult(
                    matched_reference=fb_key,
                    exact_physics_match=True,
                    physics_mismatches=[],
                    rule_violations=rule_violations,
                    info=info,
                )
            else:
                # Keep best-candidate mismatches, also note fallback failure
                rule_violations.append(f"Exact match to reference failed; fallback '{fb_key}' also mismatched")
        else:
            rule_violations.append(f"Configured fallback reference '{fb_key}' not found in index")

    # Anti-cheat checks
    try:
        # Provide minimal context to the anti-cheat runner
        ac_info = dict(info)
        ac_info['matched_reference'] = cmp.matched_key
        ac_info['exact_physics_match'] = cmp.exact_match
        ac_info['violations'] = rule_violations
        checks = run_anti_cheat_checks(submitted_car_root, ac_info, rulebook)
        info['anti_cheat'] = checks
        # Promote any anti-cheat fails into rule_violations to affect overall status
        fails = [c for c in checks if str(c.get('status','')).lower() == 'fail']
        if fails:
            rule_violations.append(f"Anti-cheat failures: {len(fails)}")
    except Exception:
        pass

    for dup_path, dup_section in ini_duplicate_sections:
        try:
            rel = dup_path.relative_to(submitted_car_root)
            rel_str = str(rel)
        except Exception:
            rel_str = str(dup_path.name)
        rule_violations.append(f"Duplicate INI section '{dup_section}' detected in {rel_str}")

    return ValidationResult(
        matched_reference=cmp.matched_key,
        exact_physics_match=cmp.exact_match,
        physics_mismatches=cmp.mismatches if not cmp.exact_match else [],
        rule_violations=rule_violations,
        info=info,
    )
