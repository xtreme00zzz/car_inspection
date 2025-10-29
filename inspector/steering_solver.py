from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple

from .ini_parser import read_ini, get_float, get_tuple_of_floats, get_str


def _vec_sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def _vec_add(a, b):
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])


def _vec_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _vec_cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _vec_len(a):
    return math.sqrt(_vec_dot(a, a))


def _vec_scale(a, s: float):
    return (a[0]*s, a[1]*s, a[2]*s)


def _vec_norm(a):
    l = _vec_len(a)
    if l == 0:
        return (0.0, 0.0, 0.0)
    return (a[0]/l, a[1]/l, a[2]/l)


def _rotate_around_axis(point, axis_p1, axis_p2, angle_rad):
    # Rodrigues rotation around axis passing through axis_p1 -> axis_p2
    # Translate so axis_p1 is origin
    p = _vec_sub(point, axis_p1)
    k = _vec_norm(_vec_sub(axis_p2, axis_p1))
    cos = math.cos(angle_rad)
    sin = math.sin(angle_rad)
    term1 = _vec_scale(p, cos)
    term2 = _vec_scale(_vec_cross(k, p), sin)
    term3 = _vec_scale(k, _vec_dot(k, p) * (1 - cos))
    rotated = _vec_add(_vec_add(term1, term2), term3)
    # Translate back
    return _vec_add(rotated, axis_p1)


def _safe_tuple(v) -> Optional[Tuple[float, float, float]]:
    if isinstance(v, tuple) and len(v) == 3:
        return (float(v[0]), float(v[1]), float(v[2]))
    return None


def solve_true_steer_angles(car_root: Path) -> Optional[Tuple[float, float]]:
    """
    Attempt to compute more faithful inner/outer max steering angles from geometry
    using STRUT kingpin axis and tie-rod endpoints, mapping wheel angle to tie-rod
    length via LINEAR_STEER_ROD_RATIO and steering lock.

    Returns (inner_deg, outer_deg) or None on failure.
    """
    try:
        susp = read_ini(car_root / 'data' / 'suspensions.ini')
        car_ini = read_ini(car_root / 'data' / 'car.ini')
    except Exception:
        return None
    # Only front axle steering considered
    # Determine geometry type and kingpin axis
    typ = (get_str(susp, 'FRONT', 'TYPE') or '').strip().upper()
    kp_a = kp_b = None
    if 'STRUT' in typ:
        kp_a = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'STRUT_CAR'))
        kp_b = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'STRUT_TYRE'))
    elif 'DWB' in typ or 'DOUBLE' in typ or 'WISH' in typ:
        # Approximate kingpin axis using tyre-side upper/lower ball joints
        kp_a = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'WBTYRE_TOP'))
        kp_b = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'WBTYRE_BOTTOM'))
    # Fallback to STRUT points if DWB tyre-side points missing
    if not (kp_a and kp_b):
        alt_a = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'STRUT_CAR'))
        alt_b = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'STRUT_TYRE'))
        if alt_a and alt_b:
            kp_a, kp_b = alt_a, alt_b
    tie_car = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'WBCAR_STEER'))
    tie_tyre = _safe_tuple(get_tuple_of_floats(susp, 'FRONT', 'WBTYRE_STEER'))
    if not (kp_a and kp_b and tie_car and tie_tyre):
        return None
    # Baseline tie-rod length at 0 angle
    def rod_len(theta: float) -> float:
        bt = _rotate_around_axis(tie_tyre, kp_a, kp_b, theta)
        return _vec_len(_vec_sub(tie_car, bt))

    L0 = rod_len(0.0)
    steer_lock = get_float(car_ini, 'CONTROLS', 'STEER_LOCK') or 0.0
    steer_ratio = get_float(car_ini, 'CONTROLS', 'STEER_RATIO') or 0.0
    lsr_ratio = get_float(car_ini, 'CONTROLS', 'LINEAR_STEER_ROD_RATIO') or 0.0
    if steer_ratio <= 0 or steer_lock <= 0 or lsr_ratio == 0:
        return None
    # Map steering wheel to rod displacement: assume LINEAR_STEER_ROD_RATIO is meters per rad
    psi_rad = math.radians(steer_lock)
    dL = lsr_ratio * psi_rad
    # Solve for theta where rod_len(theta) == L0 +/- dL
    def solve_for(delta_sign: float) -> Optional[float]:
        target = L0 + delta_sign * dL
        # Search in [0, max_angle] where max_angle from ratio estimate
        est_deg = (steer_lock / steer_ratio)
        est = math.radians(max(5.0, min(90.0, est_deg * 1.5)))
        a, b = 0.0, est
        fa = rod_len(a) - target
        fb = rod_len(b) - target
        # Expand b if needed up to 120 deg
        it = 0
        while fa * fb > 0 and b < math.radians(120.0) and it < 10:
            b *= 1.25
            fb = rod_len(b) - target
            it += 1
        if fa * fb > 0:
            return None
        # Bisection
        for _ in range(50):
            m = 0.5 * (a + b)
            fm = rod_len(m) - target
            if abs(fm) < 1e-6:
                return m
            if fa * fm <= 0:
                b, fb = m, fm
            else:
                a, fa = m, fm
        return 0.5 * (a + b)

    left_theta = solve_for(+1.0)
    right_theta = solve_for(-1.0)
    if left_theta is None and right_theta is None:
        return None
    def to_deg(x):
        return round(math.degrees(x), 2) if x is not None else None
    return (to_deg(left_theta) or 0.0, to_deg(right_theta) or 0.0)
