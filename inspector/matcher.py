from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Dict, List, Tuple

from .ini_parser import read_ini, get_float, get_str, get_tuple_of_floats


FloatKey = Tuple[str, str, str]  # (file, section, option)
StrKey = Tuple[str, str, str]


@dataclass
class CompareResult:
    matched_key: str | None
    exact_match: bool
    mismatches: List[str]
    candidate_scores: List[Tuple[str, int, int]]  # (key, equal_count, compared_count)


def _collect_fingerprint(car_root: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
    """
    Read selected INI files and return dict[file][section][option]=raw string for stable comparison.
    """
    files = ['car.ini', 'engine.ini', 'drivetrain.ini', 'suspensions.ini', 'tyres.ini', 'brakes.ini', 'aero.ini', 'setup.ini']
    fp: Dict[str, Dict[str, Dict[str, str]]] = {}
    for fname in files:
        p = car_root / 'data' / fname
        if not p.exists():
            continue
        parser = read_ini(p)
        secmap: Dict[str, Dict[str, str]] = {}
        for sec in parser.sections():
            # store raw strings
            secmap[sec] = {opt: parser.get(sec, opt) for opt in parser[sec]}
        fp[fname] = secmap
    return fp


def _normalize_for_exact(fp: Dict[str, Dict[str, Dict[str, str]]]) -> Dict[str, Dict[str, Dict[str, str]]]:
    """
    For exact physics matching, normalize whitespace and numeric formatting to a canonical form.
    """
    def norm_val(v: str) -> str:
        s = v.split(';', 1)[0].strip()
        # collapse multiple spaces and tabs
        while '  ' in s:
            s = s.replace('  ', ' ')
        return s

    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for fname, secs in fp.items():
        out[fname] = {}
        for sec, kv in secs.items():
            out[fname][sec] = {opt: norm_val(val) for opt, val in kv.items()}
    return out


_CAR_GRAPHICS_OFFSET_TOLERANCE = 0.12  # meters
_SUSP_GRAPHICS_OFFSET_TOLERANCE = 0.05  # meters


def _parse_float_tokens(value: str) -> List[float]:
    if value is None:
        return []
    try:
        tokens = re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', value)
        return [float(tok) for tok in tokens]
    except Exception:
        return []


def _allow_graphics_offset_relaxation(fname: str, sec: str, opt: str, submitted: str, reference: str) -> bool:
    fname_lower = (fname or '').lower()
    sec_upper = (sec or '').upper()
    opt_upper = (opt or '').upper()

    if fname_lower == 'car.ini' and sec_upper == 'BASIC' and opt_upper == 'GRAPHICS_OFFSET':
        sub_vals = _parse_float_tokens(submitted)
        ref_vals = _parse_float_tokens(reference)
        if len(sub_vals) >= 3 and len(ref_vals) >= 3:
            diffs = [abs(sub_vals[i] - ref_vals[i]) for i in range(3)]
            return max(diffs) <= _CAR_GRAPHICS_OFFSET_TOLERANCE
        return False

    if fname_lower == 'suspensions.ini' and sec_upper == 'GRAPHICS_OFFSETS':
        sub_vals = _parse_float_tokens(submitted)
        ref_vals = _parse_float_tokens(reference)
        if sub_vals and ref_vals:
            diff = abs(sub_vals[0] - ref_vals[0])
            return diff <= _SUSP_GRAPHICS_OFFSET_TOLERANCE
        return False

    return False


def exact_compare_to_index(submitted_fp: Dict[str, Dict[str, Dict[str, str]]], index: Dict[str, Dict[str, Dict[str, str]]]) -> CompareResult:
    """
    Compare a submitted car fingerprint against each reference fingerprint (normalized strings).
    Returns a CompareResult with best candidate and list of mismatches if not exact.
    """
    sub_norm = _normalize_for_exact(submitted_fp)

    best_key: str | None = None
    best_equal = -1
    best_compared = 0
    candidate_scores: List[Tuple[str, int, int]] = []
    mismatches_out: List[str] = []

    for key, ref_fp in index.items():
        ref_norm = _normalize_for_exact(ref_fp)
        equal = 0
        compared = 0
        mismatches: List[str] = []

        # Compare over union of files/sections/options present in either
        file_names = set(sub_norm.keys()) | set(ref_norm.keys())
        for fname in sorted(file_names):
            sub_secs = sub_norm.get(fname, {})
            ref_secs = ref_norm.get(fname, {})
            sec_names = set(sub_secs.keys()) | set(ref_secs.keys())
            for sec in sorted(sec_names):
                sub_opts = sub_secs.get(sec, {})
                ref_opts = ref_secs.get(sec, {})
                opt_names = set(sub_opts.keys()) | set(ref_opts.keys())
                for opt in sorted(opt_names):
                    sub_val = sub_opts.get(opt)
                    ref_val = ref_opts.get(opt)
                    if sub_val is None or ref_val is None:
                        compared += 1
                        mismatches.append(f"{fname}[{sec}] {opt}: submitted={sub_val} ref={ref_val}")
                    else:
                        compared += 1
                        if sub_val == ref_val or _allow_graphics_offset_relaxation(fname, sec, opt, sub_val, ref_val):
                            equal += 1
                        else:
                            mismatches.append(f"{fname}[{sec}] {opt}: submitted='{sub_val}' != ref='{ref_val}'")

        candidate_scores.append((key, equal, compared))
        if equal > best_equal or (equal == best_equal and compared > best_compared):
            best_equal = equal
            best_compared = compared
            best_key = key
            mismatches_out = mismatches

    exact = best_key is not None and best_equal == best_compared and best_compared > 0
    return CompareResult(matched_key=best_key, exact_match=exact, mismatches=mismatches_out, candidate_scores=candidate_scores)


def exact_compare_pair(submitted_fp: Dict[str, Dict[str, Dict[str, str]]],
                       ref_fp: Dict[str, Dict[str, Dict[str, str]]]) -> Tuple[bool, List[str], int, int]:
    """
    Compare submitted to a single reference fingerprint. Returns (exact, mismatches, equal_count, compared_count).
    """
    sub_norm = _normalize_for_exact(submitted_fp)
    ref_norm = _normalize_for_exact(ref_fp)
    equal = 0
    compared = 0
    mismatches: List[str] = []
    file_names = set(sub_norm.keys()) | set(ref_norm.keys())
    for fname in sorted(file_names):
        sub_secs = sub_norm.get(fname, {})
        ref_secs = ref_norm.get(fname, {})
        sec_names = set(sub_secs.keys()) | set(ref_secs.keys())
        for sec in sorted(sec_names):
            sub_opts = sub_secs.get(sec, {})
            ref_opts = ref_secs.get(sec, {})
            opt_names = set(sub_opts.keys()) | set(ref_opts.keys())
            for opt in sorted(opt_names):
                sub_val = sub_opts.get(opt)
                ref_val = ref_opts.get(opt)
                compared += 1
                if sub_val is None or ref_val is None:
                    mismatches.append(f"{fname}[{sec}] {opt}: submitted={sub_val} ref={ref_val}")
                elif sub_val == ref_val or _allow_graphics_offset_relaxation(fname, sec, opt, sub_val, ref_val):
                    equal += 1
                else:
                    mismatches.append(f"{fname}[{sec}] {opt}: submitted='{sub_val}' != ref='{ref_val}'")
    exact = (equal == compared) and compared > 0
    return exact, mismatches, equal, compared


def build_fingerprint_index(reference_root: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for car_dir in sorted(reference_root.iterdir()):
        if not car_dir.is_dir():
            continue
        fp = _collect_fingerprint(car_dir)
        if fp:
            out[car_dir.name] = fp
    return out
