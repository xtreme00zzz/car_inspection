from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import json
import shutil
import re

from .ini_parser import read_ini, get_float, get_str


def _write_ini(parser, path: Path) -> None:
    # Simple writer; note this will drop comments/formatting
    with path.open('w', encoding='utf-8') as f:
        parser.write(f)


def _clamp(value: float, lo: Optional[float], hi: Optional[float]) -> float:
    if lo is not None and value < lo:
        value = lo
    if hi is not None and value > hi:
        value = hi
    return value


SERIES_PREFIX = 'EFVD'
SERIES_PREFIX_LOWER = SERIES_PREFIX.lower()
KNOWN_PREFIXES = ('efvd', 'efdc', 'vdc')


def _strip_known_prefix(text: str) -> str:
    if not isinstance(text, str):
        return ''
    lowered = text.lower()
    for prefix in KNOWN_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix):]
        if lowered.startswith(prefix + '_') or lowered.startswith(prefix + '-'):
            return text[len(prefix) + 1:]
        if lowered.startswith(prefix + ' '):
            return text[len(prefix) + 1:]
    return text


def _prefixed_display_name(base: str) -> str:
    base_stripped = _strip_known_prefix(base or '').strip()
    if not base_stripped:
        base_stripped = 'Entry'
    return f"{SERIES_PREFIX} {base_stripped}".strip()


def _prefixed_folder_name(base: str) -> str:
    raw = _strip_known_prefix(base or '').strip(' _-.')
    if not raw:
        raw = 'entry'
    slug = raw.replace('-', '_')
    slug = re.sub(r'[^A-Za-z0-9_]+', '_', slug)
    slug = re.sub(r'_+', '_', slug)
    slug = slug.strip('_').lower()
    if slug and not slug.startswith(SERIES_PREFIX_LOWER):
        slug = f"{SERIES_PREFIX_LOWER}_{slug}"
    if not slug:
        slug = SERIES_PREFIX_LOWER
    return slug


def _ensure_kn5_stem(stem: str, base_slug: str) -> str:
    stripped = _strip_known_prefix(stem or '').lstrip('_-')
    if not stripped:
        stripped = base_slug[len(SERIES_PREFIX_LOWER) + 1:] if base_slug.startswith(f"{SERIES_PREFIX_LOWER}_") else base_slug
    candidate = f"{SERIES_PREFIX_LOWER}_{stripped}" if not stem.lower().startswith(SERIES_PREFIX_LOWER) else stem
    candidate = candidate.replace('__', '_').strip('_')
    if not candidate.startswith(SERIES_PREFIX_LOWER):
        candidate = f"{SERIES_PREFIX_LOWER}_{candidate}"
    return candidate


def _choose_base_title(result: Any, folder_name: str) -> str:
    candidates: list[str] = []
    info = getattr(result, 'info', None)
    if isinstance(info, dict):
        ui = info.get('ui')
        if isinstance(ui, dict):
            ui_name = ui.get('name')
            if isinstance(ui_name, str) and ui_name.strip():
                candidates.append(ui_name.strip())
        car_ini_name = info.get('car_ini_screen_name')
        if isinstance(car_ini_name, str) and car_ini_name.strip():
            candidates.append(car_ini_name.strip())
        submitted = info.get('submitted_car_name')
        if isinstance(submitted, str) and submitted.strip():
            candidates.append(submitted.strip().replace('_', ' '))
    if folder_name:
        candidates.append(folder_name.replace('_', ' ').strip())
    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    return folder_name or SERIES_PREFIX


def _update_kn5_references(car_root: Path, rename_map: Dict[str, str]) -> list[str]:
    changes: list[str] = []
    data_dir = car_root / 'data'
    models = data_dir / 'models.ini'
    if models.exists():
        try:
            parser = read_ini(models)
            updated = False
            for section in parser.sections():
                cur = get_str(parser, section, 'FILE')
                if cur and cur in rename_map:
                    parser[section]['FILE'] = rename_map[cur]
                    changes.append(f"data/models.ini:{section}:FILE -> {rename_map[cur]}")
                    updated = True
            if updated:
                _write_ini(parser, models)
        except Exception:
            pass
    lods = data_dir / 'lods.ini'
    if lods.exists():
        try:
            content = lods.read_text(encoding='utf-8', errors='ignore')
            new_content = content
            for old, new in rename_map.items():
                new_content = new_content.replace(old, new)
            if new_content != content:
                lods.write_text(new_content, encoding='utf-8')
                changes.append("data/lods.ini updated for KN5 names")
        except Exception:
            pass
    ext_cfg = car_root / 'extension' / 'ext_config.ini'
    if ext_cfg.exists():
        try:
            content = ext_cfg.read_text(encoding='utf-8', errors='ignore')
            new_content = content
            for old, new in rename_map.items():
                new_content = new_content.replace(old, new)
            if new_content != content:
                ext_cfg.write_text(new_content, encoding='utf-8')
                changes.append("extension/ext_config.ini updated for KN5 names")
        except Exception:
            pass
    return changes


def _rename_kn5_files(car_root: Path, base_slug: str) -> list[str]:
    changes: list[str] = []
    rename_map: Dict[str, str] = {}
    for kn5 in sorted(car_root.glob('*.kn5')):
        stem_lower = kn5.stem.lower()
        if stem_lower in {'collider', 'driver'}:
            continue
        new_stem = _ensure_kn5_stem(kn5.stem, base_slug)
        if new_stem == kn5.stem:
            continue
        target = kn5.with_name(new_stem + kn5.suffix)
        counter = 1
        while target.exists():
            target = kn5.with_name(f"{new_stem}_{counter}{kn5.suffix}")
            counter += 1
        try:
            target = kn5.rename(target)
            rename_map[kn5.name] = target.name
            changes.append(f"KN5 renamed: {kn5.name} -> {target.name}")
        except Exception:
            continue
    if rename_map:
        changes.extend(_update_kn5_references(car_root, rename_map))
    return changes


def _fix_car_ini(car_data: Path,
                 exp_min_mass: Optional[float],
                 exp_front_bias: Optional[float],
                 exp_max_steer_deg: Optional[float],
                 target_screen_name: Optional[str]) -> list[str]:
    changed: list[str] = []
    p = car_data / 'car.ini'
    try:
        parser = read_ini(p)
    except FileNotFoundError:
        return changed
    # Name
    try:
        if target_screen_name:
            current = get_str(parser, 'INFO', 'SCREEN_NAME')
            if (current or '').strip() != target_screen_name:
                if not parser.has_section('INFO'):
                    parser.add_section('INFO')
                parser['INFO']['SCREEN_NAME'] = target_screen_name
                changed.append(f"car.ini:INFO:SCREEN_NAME -> {target_screen_name}")
    except Exception:
        pass
    # Mass
    if exp_min_mass is not None:
        try:
            mass = get_float(parser, 'BASIC', 'TOTALMASS')
            if mass is not None and mass < exp_min_mass:
                parser['BASIC']['TOTALMASS'] = str(exp_min_mass)
                changed.append(f"car.ini:BASIC:TOTALMASS -> {exp_min_mass}")
        except Exception:
            pass
    # Steering
    if exp_max_steer_deg is not None:
        try:
            sr = get_float(parser, 'CONTROLS', 'STEER_RATIO') or 0.0
            sl = get_float(parser, 'CONTROLS', 'STEER_LOCK') or 0.0
            if sr > 0:
                # target lock = exp_max_steer_deg * STEER_RATIO
                target = float(exp_max_steer_deg) * sr
                if sl > target + 1e-6:
                    parser['CONTROLS']['STEER_LOCK'] = f"{target:.3f}"
                    changed.append(f"car.ini:CONTROLS:STEER_LOCK -> {target:.3f}")
        except Exception:
            pass
    if changed:
        _write_ini(parser, p)
    return changed


def _fix_suspensions_ini(car_data: Path, exp_front_bias: Optional[float]) -> list[str]:
    changed: list[str] = []
    p = car_data / 'suspensions.ini'
    try:
        parser = read_ini(p)
    except FileNotFoundError:
        return changed
    if exp_front_bias is not None:
        try:
            cg = get_float(parser, 'BASIC', 'CG_LOCATION')
            # overwrite if not within tolerance
            if (cg is None) or (abs(cg - exp_front_bias) > 0.0001):
                parser['BASIC']['CG_LOCATION'] = f"{float(exp_front_bias):.6f}"
                changed.append(f"suspensions.ini:BASIC:CG_LOCATION -> {float(exp_front_bias):.6f}")
        except Exception:
            pass
    if changed:
        _write_ini(parser, p)
    return changed


def _fix_tyres_ini(car_data: Path,
                   front_range_mm: Optional[Tuple[int, int]],
                   rear_max_mm: Optional[int]) -> list[str]:
    changed: list[str] = []
    p = car_data / 'tyres.ini'
    try:
        parser = read_ini(p)
    except FileNotFoundError:
        return changed
    def set_width(sec: str, v_m: float):
        try:
            parser[sec]['WIDTH'] = f"{v_m:.3f}"
        except Exception:
            pass
    for sec in parser.sections():
        name = sec.upper()
        try:
            w = parser.getfloat(sec, 'WIDTH')
        except Exception:
            w = None
        if w is None:
            continue
        # width is in meters
        if name.startswith('FRONT') and front_range_mm:
            lo, hi = front_range_mm
            lo_m = float(lo)/1000.0
            hi_m = float(hi)/1000.0
            new = _clamp(float(w), lo_m, hi_m)
            if abs(new - float(w)) > 1e-6:
                set_width(sec, new)
                changed.append(f"tyres.ini:{sec}:WIDTH -> {new:.3f}")
        if name.startswith('REAR') and rear_max_mm is not None:
            hi_m = float(rear_max_mm)/1000.0
            new = _clamp(float(w), None, hi_m)
            if abs(new - float(w)) > 1e-6:
                set_width(sec, new)
                changed.append(f"tyres.ini:{sec}:WIDTH -> {new:.3f}")
    if changed:
        _write_ini(parser, p)
    return changed


def _fix_ui_json(car_root: Path, min_year: Optional[int], target_name: Optional[str]) -> list[str]:
    changed: list[str] = []
    p = car_root / 'ui' / 'ui_car.json'
    try:
        data = json.loads(p.read_text(encoding='utf-8', errors='ignore'))
    except Exception:
        return changed
    if not isinstance(data, dict):
        return changed
    if target_name:
        try:
            current = data.get('name')
            if (current or '').strip() != target_name:
                data['name'] = target_name
                changed.append(f"ui/ui_car.json:name -> {target_name}")
        except Exception:
            pass
    if isinstance(min_year, int) and min_year > 0:
        y = data.get('year')
        try:
            if isinstance(y, int) and y < min_year:
                data['year'] = int(min_year)
                changed.append(f"ui_car.json:year -> {int(min_year)}")
        except Exception:
            pass
    if changed:
        p.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return changed


def _fix_data_files(car_root: Path, matched_ref: Optional[str], reference_index: Dict[str, Any]) -> list[str]:
    changed: list[str] = []
    if not matched_ref:
        return changed
    ref_entry = reference_index.get(matched_ref)
    if not isinstance(ref_entry, dict):
        return changed
    ref_path = Path(ref_entry.get('path', ''))
    src = ref_path / 'data'
    dst = car_root / 'data'
    if not (src.exists() and dst.exists()):
        return changed
    # Remove unexpected files, copy missing
    ref_files = {p.name for p in src.iterdir() if p.is_file()}
    dst_files = {p.name for p in dst.iterdir() if p.is_file()}
    # Remove extra
    for name in sorted(dst_files - ref_files):
        try:
            (dst / name).unlink(missing_ok=True)  # type: ignore
            changed.append(f"data/{name} removed (not in reference)")
        except Exception:
            pass
    # Copy missing
    for name in sorted(ref_files - dst_files):
        try:
            shutil.copy2(src / name, dst / name)
            changed.append(f"data/{name} added from reference")
        except Exception:
            pass
    return changed


def _fix_skins(car_root: Path, enforce_one: bool, max_skin_mb: Optional[int]) -> list[str]:
    changed: list[str] = []
    skins = car_root / 'skins'
    if not skins.exists():
        return changed
    # Keep only first skin if enforce_one
    if enforce_one:
        kept: Optional[Path] = None
        for d in sorted(p for p in skins.iterdir() if p.is_dir()):
            if kept is None:
                kept = d
                continue
            # move to analysis/removed_skins
            target = car_root / 'analysis' / 'removed_skins' / d.name
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(d), str(target))
                changed.append(f"skins/{d.name} moved to analysis/removed_skins")
            except Exception:
                pass
    # Compress/downscale large skin folders if max_skin_mb specified
    if max_skin_mb is not None and max_skin_mb > 0:
        try:
            from PIL import Image
            max_dim = 4096
            # Iterate remaining skins
            for d in sorted(p for p in skins.iterdir() if p.is_dir()):
                # simple image compression pass
                for tex in d.rglob('*'):
                    if tex.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
                        continue
                    try:
                        im = Image.open(str(tex))
                        w, h = im.width, im.height
                        resized = False
                        if w > max_dim or h > max_dim:
                            ratio = min(max_dim / float(w), max_dim / float(h))
                            nw, nh = int(w * ratio), int(h * ratio)
                            im = im.resize((nw, nh), Image.LANCZOS)
                            resized = True
                        # Save with decent compression
                        if tex.suffix.lower() == '.png':
                            im.save(str(tex), format='PNG', optimize=True, compress_level=6)
                        else:
                            im = im.convert('RGB')
                            im.save(str(tex), format='JPEG', quality=85, optimize=True)
                        if resized:
                            changed.append(f"{tex.relative_to(car_root)} resized")
                    except Exception:
                        continue
        except Exception:
            # Pillow not available; skip image compression
            pass
    return changed


def fix_issues(car_root: Path,
               result: Any,
               rulebook: Any,
               reference_index: Dict[str, Any],
               force_reference: bool = False) -> Tuple[Path, list[str]]:
    """
    Create a fixed copy of car_root applying automated fixes focused on PHYSICS only.
    Returns (fixed_car_path, list_of_changes)
    """
    src = Path(car_root)
    base_title = _choose_base_title(result, src.name)
    display_name = _prefixed_display_name(base_title)
    base_slug = _prefixed_folder_name(base_title)
    work_name = f"{base_slug}_fixed"
    work = src.parent / work_name
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(src, work)

    changes: list[str] = []
    if not src.name.lower().startswith(SERIES_PREFIX_LOWER):
        changes.append(f"Folder renamed to {work.name}")
    data = work / 'data'

    # Fix physics files only
    changes += _fix_car_ini(data, getattr(rulebook, 'min_total_mass_kg', None),
                            getattr(rulebook, 'enforce_front_bias', None),
                            getattr(rulebook, 'max_steer_angle_deg', None),
                            target_screen_name=display_name)
    changes += _fix_suspensions_ini(data, getattr(rulebook, 'enforce_front_bias', None))
    changes += _fix_tyres_ini(data,
                              getattr(rulebook, 'enforce_front_tyre_range_mm', None),
                              getattr(rulebook, 'enforce_rear_tyre_max_mm', None))

    # UI metadata
    changes += _fix_ui_json(work, getattr(rulebook, 'min_year', None), display_name)
    # KN5 filenames (with reference updates)
    changes += _rename_kn5_files(work, base_slug)

    # Optionally force exact physics match by replacing data/* from matched reference
    if force_reference:
        ref_key = getattr(result, 'matched_reference', None)
        ref_entry = reference_index.get(ref_key) if ref_key else None
        if isinstance(ref_entry, dict):
            ref_path = Path(ref_entry.get('path', ''))
            src_data = ref_path / 'data'
            dst_data = work / 'data'
            if src_data.exists():
                try:
                    shutil.rmtree(dst_data, ignore_errors=True)
                    shutil.copytree(src_data, dst_data)
                    changes.append(f"data/* replaced from reference '{ref_key}'")
                except Exception:
                    pass

    return work, changes


def plan_physics_changes(car_root: Path, rulebook: Any) -> list[str]:
    """Compute the list of physics changes that would be applied, without modifying files."""
    planned: list[str] = []
    data = Path(car_root) / 'data'
    # car.ini
    try:
        p = data / 'car.ini'
        parser = read_ini(p)
        # Mass
        exp_min_mass = getattr(rulebook, 'min_total_mass_kg', None)
        if exp_min_mass is not None:
            mass = get_float(parser, 'BASIC', 'TOTALMASS')
            if mass is not None and mass < exp_min_mass:
                planned.append(f"car.ini:BASIC:TOTALMASS -> {exp_min_mass}")
        # Steering
        exp_max_steer_deg = getattr(rulebook, 'max_steer_angle_deg', None)
        if exp_max_steer_deg is not None:
            sr = get_float(parser, 'CONTROLS', 'STEER_RATIO') or 0.0
            sl = get_float(parser, 'CONTROLS', 'STEER_LOCK') or 0.0
            if sr > 0:
                target = float(exp_max_steer_deg) * sr
                if sl > target + 1e-6:
                    planned.append(f"car.ini:CONTROLS:STEER_LOCK -> {target:.3f}")
    except Exception:
        pass
    # suspensions.ini
    try:
        p = data / 'suspensions.ini'
        parser = read_ini(p)
        exp_front_bias = getattr(rulebook, 'enforce_front_bias', None)
        if exp_front_bias is not None:
            cg = get_float(parser, 'BASIC', 'CG_LOCATION')
            if (cg is None) or (abs(cg - exp_front_bias) > 0.0001):
                planned.append(f"suspensions.ini:BASIC:CG_LOCATION -> {float(exp_front_bias):.6f}")
    except Exception:
        pass
    # tyres.ini
    try:
        p = data / 'tyres.ini'
        parser = read_ini(p)
        front_range = getattr(rulebook, 'enforce_front_tyre_range_mm', None)
        rear_max = getattr(rulebook, 'enforce_rear_tyre_max_mm', None)
        for sec in parser.sections():
            name = sec.upper()
            try:
                w = parser.getfloat(sec, 'WIDTH')
            except Exception:
                w = None
            if w is None:
                continue
            if name.startswith('FRONT') and front_range:
                lo, hi = front_range
                lo_m = float(lo)/1000.0
                hi_m = float(hi)/1000.0
                new = _clamp(float(w), lo_m, hi_m)
                if abs(new - float(w)) > 1e-6:
                    planned.append(f"tyres.ini:{sec}:WIDTH -> {new:.3f}")
            if name.startswith('REAR') and rear_max is not None:
                hi_m = float(rear_max)/1000.0
                new = _clamp(float(w), None, hi_m)
                if abs(new - float(w)) > 1e-6:
                    planned.append(f"tyres.ini:{sec}:WIDTH -> {new:.3f}")
    except Exception:
        pass
    return planned
