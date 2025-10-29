from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import hashlib

from .ini_parser import read_ini, get_float, get_int, get_str, get_tuple_of_floats


@dataclass
class TyreCompound:
    name: str
    short_name: Optional[str]
    width_front: Optional[float]
    width_rear: Optional[float]
    radius_front: Optional[float]
    radius_rear: Optional[float]
    dx_ref: Optional[float]
    dy_ref: Optional[float]


@dataclass
class ReferenceCar:
    key: str  # folder name
    path: str
    ui: Dict[str, Any]
    # Physics summary
    steer_lock: Optional[float]
    steer_ratio: Optional[float]
    steer_max_wheel_deg: Optional[float]
    total_mass: Optional[float]
    inertia: Optional[tuple]
    wheelbase: Optional[float]
    front_track: Optional[float]
    rear_track: Optional[float]
    cg_location: Optional[float]
    fuel_tank_pos: Optional[tuple]
    drivetrain_type: Optional[str]
    gear_count: Optional[int]
    gears: List[float]
    final_ratio: Optional[float]
    engine_inertia: Optional[float]
    engine_limiter: Optional[float]
    wastegate_primary: Optional[float]
    wastegate_secondary: Optional[float]
    turbo_boost_threshold: Optional[float]
    rpm_damage_threshold: Optional[float]
    brake_front_share: Optional[float]
    wings: List[str]
    lods_ini_present: bool
    cm_lods_triangles: Dict[str, int]
    colliders: List[Dict[str, float]]
    tyre_compounds: List[TyreCompound]
    hashed_files: Dict[str, str]


def _sha1_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha1()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _read_ui(ui_dir: Path) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    json_path = ui_dir / 'ui_car.json'
    if json_path.exists():
        try:
            import json
            with json_path.open('r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
        except Exception:
            data = {}
    return data


def _read_tyre_compounds(tyres_ini_path: Path) -> List[TyreCompound]:
    compounds: List[TyreCompound] = []
    if not tyres_ini_path.exists():
        return compounds
    parser = read_ini(tyres_ini_path)

    # Heuristic: the file can contain multiple compound sections pairs. We'll scan sequentially
    # reading NAME/SHORT_NAME on any section; and capture first FR/REAR in each run.
    current_name: Optional[str] = None
    current_short: Optional[str] = None
    cur_front: Dict[str, float] = {}
    cur_rear: Dict[str, float] = {}

    # Preserve section order
    for section in parser.sections():
        if 'NAME' in parser[section] or 'SHORT_NAME' in parser[section]:
            # flush previous if present
            if current_name:
                compounds.append(
                    TyreCompound(
                        name=current_name,
                        short_name=current_short,
                        width_front=cur_front.get('WIDTH'),
                        width_rear=cur_rear.get('WIDTH'),
                        radius_front=cur_front.get('RADIUS'),
                        radius_rear=cur_rear.get('RADIUS'),
                        dx_ref=cur_front.get('DX_REF') or cur_rear.get('DX_REF'),
                        dy_ref=cur_front.get('DY_REF') or cur_rear.get('DY_REF'),
                    )
                )
                cur_front, cur_rear = {}, {}
            current_name = get_str(parser, section, 'NAME') or current_name
            current_short = get_str(parser, section, 'SHORT_NAME') or current_short
            continue
        # Front/rear blocks
        if section.upper().startswith('FRONT'):
            for key in ('WIDTH', 'RADIUS', 'RIM_RADIUS', 'DX_REF', 'DY_REF'):
                val = get_float(parser, section, key)
                if val is not None:
                    cur_front[key] = val
        if section.upper().startswith('REAR'):
            for key in ('WIDTH', 'RADIUS', 'RIM_RADIUS', 'DX_REF', 'DY_REF'):
                val = get_float(parser, section, key)
                if val is not None:
                    cur_rear[key] = val
    if current_name:
        compounds.append(
            TyreCompound(
                name=current_name,
                short_name=current_short,
                width_front=cur_front.get('WIDTH'),
                width_rear=cur_rear.get('WIDTH'),
                radius_front=cur_front.get('RADIUS'),
                radius_rear=cur_rear.get('RADIUS'),
                dx_ref=cur_front.get('DX_REF') or cur_rear.get('DX_REF'),
                dy_ref=cur_front.get('DY_REF') or cur_rear.get('DY_REF'),
            )
        )
    return compounds


def build_reference_index(reference_root: Path) -> Dict[str, Any]:
    index: Dict[str, Any] = {}
    for car_dir in sorted(reference_root.iterdir()):
        if not car_dir.is_dir():
            continue
        key = car_dir.name
        data_dir = car_dir / 'data'
        ui_dir = car_dir / 'ui'
        try:
            ui = _read_ui(ui_dir)

            car_ini = read_ini(data_dir / 'car.ini')
            susp_ini = read_ini(data_dir / 'suspensions.ini')
            tyres_ini_path = data_dir / 'tyres.ini'
            tyres_compounds = _read_tyre_compounds(tyres_ini_path)
            engine_ini = read_ini(data_dir / 'engine.ini')
            drive_ini = read_ini(data_dir / 'drivetrain.ini')
            brakes_ini = read_ini(data_dir / 'brakes.ini')

            total_mass = get_float(car_ini, 'BASIC', 'TOTALMASS')
            inertia = get_tuple_of_floats(car_ini, 'BASIC', 'INERTIA')
            fuel_tank_pos = get_tuple_of_floats(car_ini, 'FUELTANK', 'POSITION')

            steer_lock = get_float(car_ini, 'CONTROLS', 'STEER_LOCK')
            steer_ratio = get_float(car_ini, 'CONTROLS', 'STEER_RATIO')
            steer_max_wheel = None
            if steer_lock and steer_ratio and steer_ratio != 0:
                try:
                    steer_max_wheel = steer_lock / steer_ratio
                except Exception:
                    steer_max_wheel = None

            wheelbase = get_float(susp_ini, 'BASIC', 'WHEELBASE') or get_float(susp_ini, 'FRONT', 'WHEELBASE') or get_float(susp_ini, 'REAR', 'WHEELBASE')
            cg_location = get_float(susp_ini, 'BASIC', 'CG_LOCATION')
            front_track = get_float(susp_ini, 'FRONT', 'TRACK')
            rear_track = get_float(susp_ini, 'REAR', 'TRACK')

            drivetrain_type = get_str(drive_ini, 'TRACTION', 'TYPE')
            gear_count = get_int(drive_ini, 'GEARS', 'COUNT')
            gears: List[float] = []
            if gear_count:
                for i in range(1, gear_count + 1):
                    val = get_float(drive_ini, 'GEARS', f'GEAR_{i}')
                    if val is not None:
                        gears.append(val)
            final_ratio = get_float(drive_ini, 'GEARS', 'FINAL') or get_float(drive_ini, 'FINAL', 'RATIO') or get_float(drive_ini, 'FINAL', 'FINAL')

            engine_inertia = get_float(engine_ini, 'HEADER', 'INERTIA') or get_float(engine_ini, 'ENGINE_DATA', 'INERTIA') or get_float(engine_ini, 'ENGINE', 'INERTIA')
            engine_limiter = get_float(engine_ini, 'HEADER', 'LIMITER') or get_float(engine_ini, 'ENGINE_DATA', 'LIMITER') or get_float(engine_ini, 'ENGINE', 'LIMITER')
            wastegate_primary = get_float(engine_ini, 'TURBO', 'WASTEGATE') or get_float(engine_ini, 'HEADER', 'WASTEGATE')
            wastegate_secondary = get_float(engine_ini, 'TURBO_1', 'WASTEGATE')
            turbo_boost_threshold = get_float(engine_ini, 'DAMAGE', 'TURBO_BOOST_THRESHOLD')
            rpm_damage_threshold = get_float(engine_ini, 'DAMAGE', 'RPM_THRESHOLD')

            brake_front_share = get_float(brakes_ini, 'BRAKES', 'FRONT_SHARE') or get_float(brakes_ini, 'HEADER', 'FRONT_SHARE')

            # aero wings
            wings: List[str] = []
            aero_path = data_dir / 'aero.ini'
            if aero_path.exists():
                aero_ini = read_ini(aero_path)
                for sec in aero_ini.sections():
                    if sec.startswith('WING_'):
                        name = get_str(aero_ini, sec, 'NAME')
                        if name:
                            wings.append(name.upper())

            # LODs
            lods_ini_present = (data_dir / 'lods.ini').exists()
            cm_lods_triangles: Dict[str, int] = {}
            ui_cm = ui_dir / 'cm_lods_generation.json'
            if ui_cm.exists():
                try:
                    from .ini_parser import read_json
                    cm = read_json(ui_cm)
                    stages = cm.get('Stages') or {}
                    for k, v in stages.items():
                        try:
                            # Values are stored as stringified JSON blobs in some packs; try to parse
                            import json as _json
                            if isinstance(v, str):
                                v = _json.loads(v)
                            tc = int(v.get('trianglesCount', 0))
                            cm_lods_triangles[k] = tc
                        except Exception:
                            pass
                except Exception:
                    pass

            # colliders
            colliders: List[Dict[str, float]] = []
            coll_path = data_dir / 'colliders.ini'
            if coll_path.exists():
                coll_ini = read_ini(coll_path)
                for sec in coll_ini.sections():
                    if sec.startswith('COLLIDER_'):
                        centre = get_tuple_of_floats(coll_ini, sec, 'CENTRE')
                        size = get_tuple_of_floats(coll_ini, sec, 'SIZE')
                        if centre and size:
                            colliders.append({'cx': centre[0], 'cy': centre[1], 'cz': centre[2], 'sx': size[0], 'sy': size[1], 'sz': size[2]})

            hashed_files: Dict[str, str] = {}
            def _record_hash(p: Path):
                digest = _sha1_file(p)
                if digest:
                    rel = str(p.relative_to(car_dir)).replace('\\', '/')
                    hashed_files[rel] = digest
            if data_dir.exists():
                for p in data_dir.rglob('*'):
                    if p.is_file():
                        _record_hash(p)
            collider_kn5 = car_dir / 'collider.kn5'
            if collider_kn5.exists():
                _record_hash(collider_kn5)
            extension_dir = car_dir / 'extension'
            if extension_dir.exists():
                for p in extension_dir.rglob('*'):
                    if p.is_file():
                        _record_hash(p)

            ref = ReferenceCar(
                key=key,
                path=str(car_dir),
                ui=ui,
                steer_lock=steer_lock,
                steer_ratio=steer_ratio,
                steer_max_wheel_deg=steer_max_wheel,
                total_mass=total_mass,
                inertia=inertia,
                wheelbase=wheelbase,
                cg_location=cg_location,
                front_track=front_track,
                rear_track=rear_track,
                fuel_tank_pos=fuel_tank_pos,
                drivetrain_type=drivetrain_type,
                gear_count=gear_count,
                gears=gears,
                final_ratio=final_ratio,
                engine_inertia=engine_inertia,
                engine_limiter=engine_limiter,
                wastegate_primary=wastegate_primary,
                wastegate_secondary=wastegate_secondary,
                turbo_boost_threshold=turbo_boost_threshold,
                rpm_damage_threshold=rpm_damage_threshold,
                brake_front_share=brake_front_share,
                wings=wings,
                lods_ini_present=lods_ini_present,
                cm_lods_triangles=cm_lods_triangles,
                colliders=colliders,
                tyre_compounds=tyres_compounds,
                hashed_files=hashed_files,
            )

            index[key] = asdict(ref)
        except FileNotFoundError:
            # Skip incomplete refs
            continue
    return index


def save_index(index: Dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        json.dump(index, f, indent=2)


def load_index(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)
