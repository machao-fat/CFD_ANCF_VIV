"""Stage 4D-A-v2 developed-flow continuation and audit path.

This module is intentionally separate from the first Stage 4D developed-flow
implementation.  It treats the 60 s cases as read-only source evidence and
creates a new continuation case for each Reynolds number.  No ``setFields``
operation is performed on a continuation case.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .developed_flow import (
    DevelopedFlowError,
    ForceSample,
    _replace_scalar,
    _run_openfoam,
    audit_developed_flow_identity,
    canonical_sha,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_FLOW_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow"
SOURCE_RESULT_ROOT = PROJECT_ROOT / "results" / "06_developed_flow"
V2_FLOW_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v2"
V2_RESULT_ROOT = PROJECT_ROOT / "results" / "06_developed_flow_v2"
FIXED_TEMPLATE = PROJECT_ROOT / "cases" / "openfoam" / "fixed_cylinder"
DT_S = 0.0025
MAX_PHYSICAL_TIME_S = 240.0
TIME_TOL_S = 1.0e-8
EPSILON = 0.1


def _json_safe(value: Any) -> Any:
    """Convert internal non-finite sentinels to explicit JSON nulls."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _finite_vector(values: Iterable[float]) -> tuple[float, float, float]:
    items = tuple(float(value) for value in values)
    if len(items) != 3 or not all(math.isfinite(value) for value in items):
        raise DevelopedFlowError("force vector is not finite and three-dimensional")
    return items  # type: ignore[return-value]


def read_force_csv(path: str | Path) -> list[ForceSample]:
    """Read the immutable 0--60 s force baseline with strict identity checks."""

    target = Path(path)
    if not target.is_file():
        raise DevelopedFlowError(f"force baseline is missing: {target}")
    samples: list[ForceSample] = []
    with target.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = ["time_s", "force_x_N", "force_y_N", "force_z_N"]
        if reader.fieldnames != expected:
            raise DevelopedFlowError(f"unexpected force baseline header in {target}: {reader.fieldnames}")
        for row in reader:
            try:
                current_time = float(row["time_s"])
                force = _finite_vector((row["force_x_N"], row["force_y_N"], row["force_z_N"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise DevelopedFlowError(f"invalid force baseline row in {target}") from exc
            if not math.isfinite(current_time):
                raise DevelopedFlowError(f"non-finite force baseline time in {target}")
            samples.append(ForceSample(current_time, force))
    _validate_force_times(samples, label=str(target))
    return samples


def _validate_force_times(samples: Sequence[ForceSample], *, label: str) -> None:
    if len(samples) < 16:
        raise DevelopedFlowError(f"force history has too few samples: {label}")
    times = [sample.time_s for sample in samples]
    if any(not math.isfinite(value) for value in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise DevelopedFlowError(f"force time history is not strictly increasing: {label}")


def _force_close(left: ForceSample, right: ForceSample) -> bool:
    return all(math.isclose(a, b, rel_tol=1.0e-12, abs_tol=1.0e-8) for a, b in zip(left.force_N, right.force_N))


def merge_force_histories(
    source: Sequence[ForceSample],
    continuation: Sequence[ForceSample],
    *,
    dt_s: float = DT_S,
) -> dict[str, Any]:
    """Merge old and continuation force histories without hiding conflicts."""

    _validate_force_times(source, label="source")
    _validate_force_times(continuation, label="continuation")
    merged: list[ForceSample] = []
    duplicates = 0
    for sample in sorted([*source, *continuation], key=lambda item: item.time_s):
        if merged and abs(sample.time_s - merged[-1].time_s) <= TIME_TOL_S:
            if not _force_close(sample, merged[-1]):
                raise DevelopedFlowError(f"overlapping force timestamp has different values: {sample.time_s}")
            duplicates += 1
            continue
        merged.append(sample)
    _validate_force_times(merged, label="merged")
    diffs = np.diff(np.asarray([sample.time_s for sample in merged], dtype=float))
    if len(diffs) and np.max(np.abs(diffs - float(dt_s))) > 2.0e-6:
        raise DevelopedFlowError(f"merged force history has a time gap or unexpected spacing: max_error={float(np.max(np.abs(diffs - dt_s)))}")
    return {
        "samples": merged,
        "source_sample_count": len(source),
        "continuation_sample_count": len(continuation),
        "merged_sample_count": len(merged),
        "overlap_duplicates_removed": duplicates,
        "first_time_s": merged[0].time_s,
        "last_time_s": merged[-1].time_s,
        "max_dt_error_s": float(np.max(np.abs(diffs - float(dt_s)))) if len(diffs) else 0.0,
    }


def _write_force_csv(path: Path, samples: Sequence[ForceSample]) -> None:
    lines = ["time_s,force_x_N,force_y_N,force_z_N"]
    lines.extend(
        f"{sample.time_s:.17g},{sample.force_N[0]:.17g},{sample.force_N[1]:.17g},{sample.force_N[2]:.17g}"
        for sample in samples
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _replace_vector(text: str, pattern: str, vectors: Sequence[tuple[float, float, float]], *, label: str) -> str:
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
    if len(matches) != len(vectors):
        raise DevelopedFlowError(f"expected {len(vectors)} {label} entries, found {len(matches)}")
    cursor = 0
    output: list[str] = []
    for match, vector in zip(matches, vectors):
        output.append(text[cursor:match.start()])
        output.append(f"{match.group(1)}({vector[0]:.12g} {vector[1]:.12g} {vector[2]:.12g})")
        cursor = match.end()
    output.append(text[cursor:])
    return "".join(output)


def rewrite_initial_velocity_files(case: Path, U: float, *, epsilon: float = EPSILON) -> dict[str, Any]:
    """Make default, inlet and perturbation velocities derive from one U."""

    U = float(U)
    if not math.isfinite(U) or U <= 0.0:
        raise DevelopedFlowError("U must be positive and finite")
    default = (U, 0.0, 0.0)
    perturbation = (U, epsilon * U, 0.0)
    u_path = case / "0" / "U"
    u_text = u_path.read_text(encoding="utf-8")
    u_text = re.sub(
        r"(internalField\s+uniform\s+)\([^)]*\)",
        rf"\g<1>({U:.12g} 0 0)",
        u_text,
        count=1,
    )
    u_text, count = re.subn(
        r"(inlet\s*\{.*?value\s+uniform\s+)\([^)]*\)",
        rf"\g<1>({U:.12g} 0 0)",
        u_text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise DevelopedFlowError(f"inlet velocity entry was not found in {u_path}")
    u_path.write_text(u_text, encoding="utf-8")

    set_fields_path = case / "system" / "setFieldsDict"
    set_fields = set_fields_path.read_text(encoding="utf-8")
    set_fields = _replace_vector(
        set_fields,
        r"(volVectorFieldValue\s+U\s+)(\([^)]*\))",
        (default, perturbation),
        label="setFields velocity",
    )
    set_fields_path.write_text(set_fields, encoding="utf-8")
    return {
        "default_internal_U": list(default),
        "inlet_U": list(default),
        "perturbed_U": list(perturbation),
        "epsilon": epsilon,
        "setFields_rewritten": True,
    }


def prepare_v2_fresh_case(output: Path, U: float, *, run_id: str, end_time_s: float = 0.1) -> dict[str, Any]:
    """Create a fresh case only for the v2 initialization tests/smoke."""

    if output.exists():
        raise FileExistsError(f"refusing to overwrite v2 case: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in ("0", "constant", "system"):
        shutil.copytree(FIXED_TEMPLATE / name, output / name)
    control_path = output / "system" / "controlDict"
    control = control_path.read_text(encoding="utf-8")
    control = _replace_scalar(control, "application", "pimpleFoam")
    control = _replace_scalar(control, "endTime", format(float(end_time_s), ".12g"))
    control = _replace_scalar(control, "writePrecision", "16")
    control = _replace_scalar(control, "timePrecision", "12")
    control = re.sub(r"(?m)^(\s*magUInf\s+)[^;]+;", rf"\g<1>{float(U):.12g};", control)
    control_path.write_text(control, encoding="utf-8")
    _configure_pimple_case(output)
    velocities = rewrite_initial_velocity_files(output, U)
    provenance = {
        "run_id": run_id,
        "flow_id": f"re{int(round(float(U) / 0.01))}",
        "U_mps": float(U),
        "Re": float(U) / 0.01,
        "rho_kgpm3": 1000.0,
        "nu_m2ps": 0.01,
        "D_m": 1.0,
        "dt_s": DT_S,
        "initial_source": "fixed_cylinder_template",
        "velocity_definition": velocities,
        "setFields_called": False,
    }
    (output / "stage4d_flow_provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"case": str(output.resolve()), **provenance}


def _configure_pimple_case(case: Path) -> None:
    """Apply the existing fixed-cylinder numerical setup without hard-coded U."""

    momentum_source = PROJECT_ROOT / "cases" / "openfoam" / "single_dof_free_viv_Ur5p2_developed" / "constant" / "momentumTransport"
    target_momentum = case / "constant" / "momentumTransport"
    if momentum_source.is_file() and not target_momentum.exists():
        shutil.copy2(momentum_source, target_momentum)
    fv_solution_path = case / "system" / "fvSolution"
    fv_solution = fv_solution_path.read_text(encoding="utf-8")
    fv_solution = fv_solution.replace("PISO\n{", "PIMPLE\n{")
    if "nOuterCorrectors" not in fv_solution:
        fv_solution = fv_solution.replace("PIMPLE\n{\n", "PIMPLE\n{\n    nOuterCorrectors          1;\n", 1)
    if "UFinal" not in fv_solution:
        marker = "    }\n}\n\nPIMPLE"
        fv_solution = fv_solution.replace(marker, "    }\n\n    UFinal\n    {\n        $U;\n        relTol          0;\n    }\n}\n\nPIMPLE", 1)
    fv_solution_path.write_text(fv_solution, encoding="utf-8")
    fv_schemes_path = case / "system" / "fvSchemes"
    fv_schemes = fv_schemes_path.read_text(encoding="utf-8")
    fv_schemes = fv_schemes.replace("div(phi,U)      Gauss linear;", "div(phi,U)      Gauss linearUpwind grad(U);\n    div((nuEff*dev2(T(grad(U))))) Gauss linear;")
    fv_schemes = fv_schemes.replace("default         Gauss linear orthogonal;", "default         Gauss linear corrected;")
    fv_schemes = fv_schemes.replace("default         orthogonal;", "default         corrected;")
    fv_schemes_path.write_text(fv_schemes, encoding="utf-8")
    physical_path = case / "constant" / "physicalProperties"
    physical = physical_path.read_text(encoding="utf-8")
    if "viscosityModel" not in physical:
        physical = physical.replace("// Re =", "viscosityModel  constant;\n\n// Re =", 1)
    physical_path.write_text(physical, encoding="utf-8")


def _read_source_summary(flow_id: str) -> tuple[dict[str, Any], Path, Path]:
    summary_path = SOURCE_RESULT_ROOT / flow_id / f"{flow_id}_summary.json"
    case = SOURCE_FLOW_ROOT / flow_id
    if not summary_path.is_file() or not case.is_dir():
        raise DevelopedFlowError(f"source 60 s flow evidence is missing for {flow_id}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    audit_developed_flow_identity(summary, case=case)
    source_csv = Path(str(summary["force_history_csv"]))
    source_samples = read_force_csv(source_csv)
    if source_samples[-1].time_s < 59.9:
        raise DevelopedFlowError(f"source flow does not reach 60 s for {flow_id}")
    return summary, case, source_csv


def _prepare_continuation_case(
    *,
    flow_id: str,
    U: float,
    source_summary: Mapping[str, Any],
    source_case: Path,
    output: Path,
    run_id: str,
) -> dict[str, Any]:
    source_U = float(source_summary.get("U_mps", float("nan")))
    source_flow_id = str(source_summary.get("flow_id", ""))
    if source_flow_id != flow_id or not math.isclose(source_U, float(U), rel_tol=0.0, abs_tol=1.0e-12):
        raise DevelopedFlowError(f"cross-Re continuation source rejected: source={source_flow_id}/{source_U}, target={flow_id}/{U}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite v2 continuation case: {output}")
    final_time_name = str(source_summary["final_time_name"])
    if Path(final_time_name).name != final_time_name or not re.fullmatch(r"[0-9.eE+-]+", final_time_name):
        raise DevelopedFlowError(f"invalid source final time directory: {final_time_name}")
    source_time_dir = source_case / final_time_name
    if not source_time_dir.is_dir():
        raise DevelopedFlowError(f"source final time directory is missing: {source_time_dir}")
    output.mkdir(parents=True)
    shutil.copytree(source_case / "constant", output / "constant")
    shutil.copytree(source_case / "system", output / "system")
    shutil.copytree(source_time_dir, output / final_time_name)
    source_fields = {}
    for relative, expected in dict(source_summary["final_fields"]).items():
        source_path = source_case / relative
        if not source_path.is_file() or sha256_file(source_path) != str(expected):
            raise DevelopedFlowError(f"source final field hash changed before continuation: {relative}")
        source_fields[relative] = str(expected)
    control_path = output / "system" / "controlDict"
    control = control_path.read_text(encoding="utf-8")
    control = _replace_scalar(control, "startFrom", "latestTime")
    control = _replace_scalar(control, "startTime", format(float(source_summary["end_time_s"]), ".12g"))
    control = _replace_scalar(control, "endTime", format(float(source_summary["end_time_s"]) + 10.0, ".12g"))
    control = _replace_scalar(control, "deltaT", format(DT_S, ".12g"))
    control = _replace_scalar(control, "writePrecision", "16")
    control = _replace_scalar(control, "timePrecision", "12")
    control = re.sub(r"(?m)^(\s*magUInf\s+)[^;]+;", rf"\g<1>{float(U):.12g};", control)
    control_path.write_text(control, encoding="utf-8")
    source_force_path = Path(str(source_summary["force_history_csv"]))
    lineage = {
        "run_id": run_id,
        "flow_id": flow_id,
        "U_mps": float(U),
        "Re": float(U) / 0.01,
        "source_case": str(source_case.resolve()),
        "source_summary": str((SOURCE_RESULT_ROOT / flow_id / f"{flow_id}_summary.json").resolve()),
        "source_summary_sha256": sha256_file(SOURCE_RESULT_ROOT / flow_id / f"{flow_id}_summary.json"),
        "source_end_time_s": float(source_summary["end_time_s"]),
        "source_final_time_name": final_time_name,
        "source_final_fields": source_fields,
        "source_force_history": str(source_force_path.resolve()),
        "source_force_sha256": sha256_file(source_force_path),
        "target_case": str(output.resolve()),
        "startFrom": "latestTime",
        "setFields_called": False,
        "cross_re_source_rejected": True,
        "dt_s": DT_S,
        "max_physical_time_s": MAX_PHYSICAL_TIME_S,
    }
    (output / "continuation_lineage.json").write_text(json.dumps(lineage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return lineage


def _set_end_time(case: Path, end_time_s: float) -> None:
    path = case / "system" / "controlDict"
    text = path.read_text(encoding="utf-8")
    text = _replace_scalar(text, "endTime", format(float(end_time_s), ".12g"))
    text = _replace_scalar(text, "startFrom", "latestTime")
    path.write_text(text, encoding="utf-8")


def _centered_rms(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.sqrt(np.mean(np.square(array - np.mean(array)))))


def _raw_rms(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.sqrt(np.mean(np.square(array))))


def zero_crossing_frequency(times: Sequence[float], values: Sequence[float]) -> float:
    t = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    if len(t) != len(y) or len(t) < 16:
        return 0.0
    y = y - np.mean(y)
    crossings: list[float] = []
    for index in range(len(y) - 1):
        if y[index] <= 0.0 < y[index + 1] and y[index + 1] != y[index]:
            fraction = -y[index] / (y[index + 1] - y[index])
            crossings.append(float(t[index] + fraction * (t[index + 1] - t[index])))
    if len(crossings) < 3:
        return 0.0
    periods = np.diff(np.asarray(crossings, dtype=float))
    periods = periods[np.isfinite(periods) & (periods > 0.0)]
    if not len(periods):
        return 0.0
    return float(1.0 / np.median(periods))


def _upward_crossings(times: Sequence[float], values: Sequence[float]) -> np.ndarray:
    t = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float) - float(np.mean(values))
    crossings: list[float] = []
    for index in range(len(y) - 1):
        if y[index] <= 0.0 < y[index + 1] and y[index + 1] != y[index]:
            fraction = -y[index] / (y[index + 1] - y[index])
            crossings.append(float(t[index] + fraction * (t[index + 1] - t[index])))
    return np.asarray(crossings, dtype=float)


def _coefficients(samples: Sequence[ForceSample], *, U: float, rho: float, D: float, span: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    times = np.asarray([sample.time_s for sample in samples], dtype=float)
    denominator = 0.5 * rho * U * U * D * span
    cd = np.asarray([sample.force_N[0] / denominator for sample in samples], dtype=float)
    cl = np.asarray([sample.force_N[1] / denominator for sample in samples], dtype=float)
    if not np.all(np.isfinite(np.concatenate((times, cd, cl)))):
        raise DevelopedFlowError("force coefficients contain NaN/Inf")
    return times, cd, cl


def _window_metrics_v2(samples: Sequence[ForceSample], *, U: float, start: float, end: float, rho: float, D: float, span: float) -> dict[str, Any]:
    selected = [sample for sample in samples if start - TIME_TOL_S <= sample.time_s <= end + TIME_TOL_S]
    if len(selected) < 16:
        return {"start_time_s": start, "end_time_s": end, "samples": len(selected), "complete_cycles": 0.0, "available": False}
    times, cd, cl = _coefficients(selected, U=U, rho=rho, D=D, span=span)
    fft_frequency = _fft_frequency(times, cl, fmin=0.05 * U / D, fmax=0.35 * U / D)
    crossing_frequency = zero_crossing_frequency(times, cl)
    crossings = _upward_crossings(times, cl)
    cycles = max(0.0, float(len(crossings) - 1))
    return {
        "start_time_s": start,
        "end_time_s": end,
        "samples": len(selected),
        "complete_cycles": cycles,
        "available": cycles >= 3.0,
        "mean_Cd": float(np.mean(cd)),
        "Cd_rms": _raw_rms(cd),
        "Cd_fluctuation_rms": _centered_rms(cd),
        "legacy_Cd_rms_raw": _raw_rms(cd),
        "Cl_rms": _centered_rms(cl),
        "legacy_Cl_rms_raw": _raw_rms(cl),
        "Cl_peak_to_peak": float(np.max(cl) - np.min(cl)),
        "fft_frequency_Hz": fft_frequency,
        "zero_crossing_frequency_Hz": crossing_frequency,
        "frequency_crosscheck_relative_difference": abs(fft_frequency - crossing_frequency) / max(abs(fft_frequency), 1.0e-30),
        "St": fft_frequency * D / U if U > 0.0 else 0.0,
    }


def _fft_frequency(times: Sequence[float], values: Sequence[float], *, fmin: float, fmax: float) -> float:
    t = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    if len(t) != len(y) or len(t) < 32:
        return 0.0
    dt = float(np.median(np.diff(t)))
    if not math.isfinite(dt) or dt <= 0.0:
        return 0.0
    x = np.arange(len(y), dtype=float)
    detrended = y - np.polyval(np.polyfit(x, y, 1), x)
    # Three-cycle windows are deliberately short; use sufficient zero
    # padding for the FFT/zero-crossing cross-check rather than reporting a
    # coarse-bin frequency as if it were high precision.
    nfft = max(65536, 1 << int(math.ceil(math.log2(len(y)))))
    spectrum = np.abs(np.fft.rfft(detrended, n=nfft))
    frequencies = np.fft.rfftfreq(nfft, dt)
    mask = (frequencies >= fmin) & (frequencies <= min(fmax, 0.5 / dt))
    if not np.any(mask):
        return 0.0
    candidates = np.flatnonzero(mask)
    index = int(candidates[int(np.argmax(spectrum[mask]))])
    if 0 < index < len(spectrum) - 1:
        left, center, right = spectrum[index - 1:index + 2]
        denominator = left - 2.0 * center + right
        if abs(denominator) > 1.0e-30:
            index = float(index) + 0.5 * (left - right) / denominator
    return float(index / (nfft * dt))


def _envelope_metrics(samples: Sequence[ForceSample], *, U: float, rho: float, D: float, span: float, discard_start: float, window_2: Mapping[str, Any]) -> dict[str, Any]:
    selected = [sample for sample in samples if discard_start <= sample.time_s <= samples[-1].time_s]
    times, _, cl = _coefficients(selected, U=U, rho=rho, D=D, span=span)
    mean_cl = float(np.mean(cl))
    crossings = _upward_crossings(times, cl)
    amplitudes: list[float] = []
    for left, right in zip(crossings, crossings[1:]):
        values = cl[(times >= left) & (times <= right)] - mean_cl
        if len(values) >= 4:
            amplitudes.append(float(0.5 * (np.max(values) - np.min(values))))
    relative_changes = [abs(b - a) / max(abs(a), 1.0e-12) for a, b in zip(amplitudes, amplitudes[1:])]
    window_start = float(window_2.get("start_time_s", samples[-1].time_s))
    window_selected = [sample for sample in samples if window_start <= sample.time_s <= samples[-1].time_s]
    window_times, _, window_cl = _coefficients(window_selected, U=U, rho=rho, D=D, span=span) if len(window_selected) >= 16 else (np.asarray([]), np.asarray([]), np.asarray([]))
    window_crossings = _upward_crossings(window_times, window_cl) if len(window_times) else np.asarray([])
    window_amplitudes: list[float] = []
    for left, right in zip(window_crossings, window_crossings[1:]):
        values = window_cl[(window_times >= left) & (window_times <= right)] - float(np.mean(window_cl))
        if len(values) >= 4:
            window_amplitudes.append(float(0.5 * (np.max(values) - np.min(values))))
    window_relative_changes = [abs(b - a) / max(abs(a), 1.0e-12) for a, b in zip(window_amplitudes, window_amplitudes[1:])]
    return {
        "complete_cycle_count": max(0, len(crossings) - 1),
        "cycle_amplitudes_Cl": amplitudes,
        "envelope_relative_changes": relative_changes,
        "max_abs_envelope_change": max(relative_changes) if relative_changes else None,
        "window_cycle_amplitudes_Cl": window_amplitudes,
        "window_envelope_relative_changes": window_relative_changes,
        "window_max_abs_envelope_change": max(window_relative_changes) if window_relative_changes else None,
        "criterion_max_window_envelope_change_le_2_percent": bool(window_relative_changes) and max(window_relative_changes) <= 0.02,
    }


def analyze_force_history_v2(
    samples: Sequence[ForceSample],
    *,
    U: float,
    rho: float = 1000.0,
    D: float = 1.0,
    span: float = 1.0,
    discard_start_s: float | None = None,
    window_cycles: int = 3,
) -> dict[str, Any]:
    if not samples:
        raise DevelopedFlowError("empty v2 force history")
    _validate_force_times(samples, label="v2 analysis")
    times, _, cl = _coefficients(samples, U=U, rho=rho, D=D, span=span)
    rough_fft = _fft_frequency(times[int(len(times) * 0.5):], cl[int(len(times) * 0.5):], fmin=0.05 * U / D, fmax=0.35 * U / D)
    rough_zero = zero_crossing_frequency(times[int(len(times) * 0.5):], cl[int(len(times) * 0.5):])
    rough_frequency = rough_fft or rough_zero or 0.16 * U / D
    period = 1.0 / rough_frequency
    discard = float(discard_start_s if discard_start_s is not None else max(2.0 * period, 2.0))
    end = float(samples[-1].time_s)
    # Use one extra estimated period as a phase-alignment margin.  A window
    # of exactly 3T can contain only two complete cycles when its endpoints
    # fall between upward zero crossings.
    window_duration = float(window_cycles + 1) * period
    window_2_start = end - window_duration
    window_1_start = end - 2.0 * window_duration
    window_1 = _window_metrics_v2(samples, U=U, start=window_1_start, end=window_2_start, rho=rho, D=D, span=span)
    window_2 = _window_metrics_v2(samples, U=U, start=window_2_start, end=end, rho=rho, D=D, span=span)
    if window_1.get("available") and window_2.get("available"):
        cd_change = abs(window_2["mean_Cd"] - window_1["mean_Cd"]) / max(abs(window_1["mean_Cd"]), 1.0e-30)
        cl_change = abs(window_2["Cl_rms"] - window_1["Cl_rms"]) / max(abs(window_1["Cl_rms"]), 1.0e-30)
        frequency_change = abs(window_2["fft_frequency_Hz"] - window_1["fft_frequency_Hz"]) / max(abs(window_1["fft_frequency_Hz"]), 1.0e-30)
        peak_change = abs(window_2["Cl_peak_to_peak"] - window_1["Cl_peak_to_peak"]) / max(abs(window_1["Cl_peak_to_peak"]), 1.0e-30)
    else:
        cd_change = cl_change = frequency_change = peak_change = float("inf")
    envelope = _envelope_metrics(samples, U=U, rho=rho, D=D, span=span, discard_start=discard, window_2=window_2)
    total_crossings = _upward_crossings(times[times >= discard], cl[times >= discard])
    total_cycles = max(0.0, float(len(total_crossings) - 1))
    post_discard = cl[times >= discard]
    cl_chunk_rms = [_centered_rms(chunk) for chunk in np.array_split(post_discard, 4) if len(chunk)]
    cl_amplitude_monotonic = len(cl_chunk_rms) >= 3 and (
        all(b > a * (1.0 + 1.0e-6) for a, b in zip(cl_chunk_rms, cl_chunk_rms[1:]))
        or all(b < a * (1.0 - 1.0e-6) for a, b in zip(cl_chunk_rms, cl_chunk_rms[1:]))
    )
    crosscheck = float(window_2.get("frequency_crosscheck_relative_difference", float("inf")))
    criteria = {
        "total_complete_cycles_at_least_12": total_cycles >= 12.0,
        "three_complete_cycles_in_each_window": bool(window_1.get("available")) and bool(window_2.get("available")),
        "mean_Cd_change_le_3_percent": cd_change <= 0.03,
        "Cl_fluctuation_RMS_change_le_5_percent": cl_change <= 0.05,
        "frequency_change_le_3_percent": frequency_change <= 0.03,
        "Cl_peak_to_peak_change_le_5_percent": peak_change <= 0.05,
        "envelope_change_le_2_percent": bool(envelope["criterion_max_window_envelope_change_le_2_percent"]),
        "FFT_zero_crossing_frequency_change_le_3_percent": crosscheck <= 0.03,
        "St_in_range": 0.12 <= float(window_2.get("St", 0.0)) <= 0.22,
    }
    return {
        "total_runtime_s": end,
        "discarded_startup_transient_s": discard,
        "dominant_frequency_Hz": window_2.get("fft_frequency_Hz", 0.0),
        "zero_crossing_frequency_Hz": window_2.get("zero_crossing_frequency_Hz", 0.0),
        "St": window_2.get("St", 0.0),
        "period_s": period,
        "covered_cycles_after_transient": total_cycles,
        "window_1": window_1,
        "window_2": window_2,
        "window_relative_changes": {
            "mean_Cd": cd_change,
            "Cl_fluctuation_RMS": cl_change,
            "frequency": frequency_change,
            "Cl_peak_to_peak": peak_change,
            "FFT_zero_crossing_frequency": crosscheck,
        },
        "envelope": envelope,
        "cl_chunk_rms": cl_chunk_rms,
        "cl_amplitude_monotonic": cl_amplitude_monotonic,
        "criteria": criteria,
        "all_stable_criteria": all(criteria.values()),
        "physical_statistics_definition": {
            "Cl_rms": "sqrt(mean((Cl-mean(Cl))^2))",
            "Cd_fluctuation_rms": "sqrt(mean((Cd-mean(Cd))^2))",
            "cl_chunk_rms": "dimensionless Cl RMS after global-mean removal",
        },
    }


def _cfl_from_logs(log_paths: Sequence[Path]) -> float:
    maximum = 0.0
    for log in log_paths:
        text = log.read_text(encoding="utf-8", errors="replace")
        if any(token in text for token in ("nan", "NaN", "Inf", "FOAM FATAL ERROR")):
            raise DevelopedFlowError(f"non-finite/fatal text in {log}")
        values = [float(item) for item in re.findall(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)", text)]
        if values:
            maximum = max(maximum, max(values))
    return maximum


def _plot_diagnostics(result_dir: Path, samples: Sequence[ForceSample], stats: Mapping[str, Any], *, U: float, rho: float, D: float, span: float) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times, cd, cl = _coefficients(samples, U=U, rho=rho, D=D, span=span)
    paths: dict[str, str] = {}
    force_plot = result_dir / "force_coefficient_history.png"
    figure, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    axes[0].plot(times, cd, linewidth=0.5)
    axes[0].set_ylabel("Cd")
    axes[1].plot(times, cl, linewidth=0.5)
    axes[1].set_ylabel("Cl")
    axes[1].set_xlabel("time (s)")
    figure.tight_layout()
    figure.savefig(force_plot, dpi=140)
    plt.close(figure)
    paths["force_coefficient_history"] = str(force_plot.resolve())

    envelope_plot = result_dir / "cl_envelope.png"
    envelope = stats["envelope"]
    figure, axis = plt.subplots(figsize=(10, 4))
    amplitudes = envelope.get("cycle_amplitudes_Cl", [])
    axis.plot(np.arange(len(amplitudes)), amplitudes, marker="o", markersize=2, linewidth=0.8)
    axis.set_xlabel("cycle index after startup discard")
    axis.set_ylabel("Cl envelope amplitude")
    figure.tight_layout()
    figure.savefig(envelope_plot, dpi=140)
    plt.close(figure)
    paths["cl_envelope"] = str(envelope_plot.resolve())

    convergence_plot = result_dir / "window_convergence.png"
    figure, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    history = json.loads((result_dir / "convergence_history.json").read_text(encoding="utf-8"))
    evaluations = history.get("evaluations", [])
    x = [item["end_time_s"] for item in evaluations]
    axes[0].plot(x, [item["statistics"].get("window_relative_changes", {}).get("Cl_fluctuation_RMS", np.nan) for item in evaluations], marker="o", label="Cl RMS change")
    axes[0].axhline(0.05, color="r", linestyle="--")
    axes[0].plot(x, [item["statistics"].get("window_relative_changes", {}).get("Cl_peak_to_peak", np.nan) for item in evaluations], marker="x", label="Cl peak-to-peak change")
    axes[0].axhline(0.05, color="r", linestyle=":")
    axes[0].legend()
    axes[0].set_ylabel("relative change")
    axes[1].plot(x, [item["statistics"].get("window_2", {}).get("St", np.nan) for item in evaluations], marker="o")
    axes[1].axhspan(0.12, 0.22, color="green", alpha=0.15)
    axes[1].set_ylabel("St")
    axes[1].set_xlabel("continuation end time (s)")
    figure.tight_layout()
    figure.savefig(convergence_plot, dpi=140)
    plt.close(figure)
    paths["window_convergence"] = str(convergence_plot.resolve())
    return paths


def run_v2_flow_case(
    *,
    flow_id: str,
    U: float,
    root: Path = V2_FLOW_ROOT,
    result_root: Path = V2_RESULT_ROOT,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Continue one immutable 60 s source case to an adaptive 240 s limit."""

    run_id = run_id or f"stage4d_a_v2_{flow_id}_{uuid.uuid4().hex[:8]}"
    source_summary, source_case, source_csv = _read_source_summary(flow_id)
    source_samples = read_force_csv(source_csv)
    target_case = root / flow_id
    result_dir = result_root / flow_id
    result_dir.mkdir(parents=True, exist_ok=True)
    lineage = _prepare_continuation_case(
        flow_id=flow_id,
        U=U,
        source_summary=source_summary,
        source_case=source_case,
        output=target_case,
        run_id=run_id,
    )
    check = _run_openfoam(target_case, "checkMesh_continuation", timeout_s=300.0)
    if check["return_code"] != 0 or "Mesh OK" not in Path(check["log"]).read_text(encoding="utf-8", errors="replace"):
        raise DevelopedFlowError(f"continuation checkMesh failed for {flow_id}")
    merged = {"samples": list(source_samples), "source_sample_count": len(source_samples), "continuation_sample_count": 0, "merged_sample_count": len(source_samples), "overlap_duplicates_removed": 0, "first_time_s": source_samples[0].time_s, "last_time_s": source_samples[-1].time_s, "max_dt_error_s": 0.0}
    source_discard = float(source_summary.get("statistics", {}).get("discarded_startup_transient_s", 0.0))
    evaluations: list[dict[str, Any]] = []
    stable_consecutive = 0
    runs: list[dict[str, Any]] = []
    continuation_end = float(source_samples[-1].time_s)
    while True:
        stats = analyze_force_history_v2(merged["samples"], U=U, discard_start_s=source_discard)
        # The immutable 60 s source is a baseline, not one of the three
        # continuation assessment points required for v2 admission.
        if continuation_end <= float(source_samples[-1].time_s) + TIME_TOL_S:
            stable_consecutive = 0
        else:
            stable_consecutive = stable_consecutive + 1 if stats["all_stable_criteria"] else 0
        evaluations.append({"end_time_s": continuation_end, "stable_consecutive": stable_consecutive, "statistics": stats})
        if stable_consecutive >= 3:
            break
        if continuation_end >= MAX_PHYSICAL_TIME_S - DT_S:
            break
        period = float(stats["period_s"])
        block_duration = max(2.0 * period, 4.0 * DT_S)
        block_steps = max(1, int(math.ceil(block_duration / DT_S - 1.0e-12)))
        next_end = min(MAX_PHYSICAL_TIME_S, continuation_end + block_steps * DT_S)
        next_end = round(next_end / DT_S) * DT_S
        if next_end <= continuation_end + 0.5 * DT_S:
            next_end = min(MAX_PHYSICAL_TIME_S, continuation_end + DT_S)
        _set_end_time(target_case, next_end)
        solver = _run_openfoam(target_case, f"pimpleFoam_cont_{next_end:.6f}s", timeout_s=3600.0)
        runs.append(solver)
        if solver["return_code"] != 0:
            raise DevelopedFlowError(f"continuation pimpleFoam failed for {flow_id}: {solver}")
        continuation_samples, force_paths = _collect_continuation_forces(target_case)
        merged = merge_force_histories(source_samples, continuation_samples)
        merged["force_paths"] = [str(path.resolve()) for path in force_paths]
        _write_force_csv(result_dir / "force_history_merged.csv", merged["samples"])
        continuation_end = float(merged["last_time_s"])
        if continuation_end > MAX_PHYSICAL_TIME_S + TIME_TOL_S:
            raise DevelopedFlowError(f"v2 continuation exceeded 240 s for {flow_id}: {continuation_end}")
    _write_force_csv(result_dir / "force_history_merged.csv", merged["samples"])
    stats = evaluations[-1]["statistics"]
    continuation_hash = sha256_file(result_dir / "force_history_merged.csv")
    final_time_value, final_dir = max(
        ((float(child.name), child) for child in target_case.iterdir() if child.is_dir() and re.fullmatch(r"[0-9.eE+-]+", child.name)),
        key=lambda item: item[0],
    )
    required = [final_dir / name for name in ("U", "p", "phi", Path("uniform") / "time")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise DevelopedFlowError(f"v2 final field is incomplete for {flow_id}: {missing}")
    final_fields = {str(path.relative_to(target_case)).replace("\\", "/"): sha256_file(path) for path in required}
    max_cfl = max(float(source_summary.get("max_cfl", 0.0)), _cfl_from_logs([Path(item["log"]) for item in runs]))
    lineage.update({
        "continuation_blocks": len(runs),
        "continuation_end_time_s": continuation_end,
        "continuation_force_sha256": continuation_hash,
        "continuation_sample_count": merged["continuation_sample_count"],
        "merged_sample_count": merged["merged_sample_count"],
        "merged_force_sha256": continuation_hash,
        "merged_force_file": str((result_dir / "force_history_merged.csv").resolve()),
        "source_force_sha256_after_run": sha256_file(source_csv),
        "source_force_unchanged": sha256_file(source_csv) == lineage["source_force_sha256"],
    })
    (result_dir / "continuation_lineage.json").write_text(json.dumps(lineage, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    convergence = {
        "status": "developed" if stats["all_stable_criteria"] and evaluations[-1]["stable_consecutive"] >= 3 else "blocked",
        "evaluation_count": len(evaluations),
        "required_consecutive_stable_points": 3,
        "evaluations": evaluations,
    }
    (result_dir / "convergence_history.json").write_text(json.dumps(_json_safe(convergence), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    plot_paths = _plot_diagnostics(result_dir, merged["samples"], stats, U=U, rho=1000.0, D=1.0, span=1.0)
    physical_identity = {
        "flow_id": flow_id,
        "U_mps": U,
        "Re": U / 0.01,
        "rho_kgpm3": 1000.0,
        "nu_m2ps": 0.01,
        "D_m": 1.0,
        "dt_s": DT_S,
        "source_final_fields": lineage["source_final_fields"],
        "source_force_sha256": lineage["source_force_sha256"],
        "merged_force_sha256": continuation_hash,
        "final_fields": final_fields,
        "end_time_s": continuation_end,
        "statistics": {
            "dominant_frequency_Hz": stats["dominant_frequency_Hz"],
            "zero_crossing_frequency_Hz": stats["zero_crossing_frequency_Hz"],
            "St": stats["St"],
            "mean_Cd": stats["window_2"].get("mean_Cd"),
            "Cl_rms": stats["window_2"].get("Cl_rms"),
            "criteria": stats["criteria"],
        },
    }
    developed_sha = canonical_sha(physical_identity)
    summary = {
        "status": "developed" if convergence["status"] == "developed" else "blocked",
        "flow_id": flow_id,
        "U_mps": U,
        "Re": U / 0.01,
        "source_status": source_summary.get("status"),
        "total_runtime_s": continuation_end,
        "source_runtime_s": source_summary.get("end_time_s"),
        "continuation_runtime_s": continuation_end - float(source_summary.get("end_time_s", 0.0)),
        "statistics": stats,
        "max_cfl": max_cfl,
        "checkMesh": check,
        "solver_runs": runs,
        "final_time_name": final_dir.name,
        "final_fields": final_fields,
        "force_history_merged_csv": str((result_dir / "force_history_merged.csv").resolve()),
        "merged_force_sha256": continuation_hash,
        "convergence_history": str((result_dir / "convergence_history.json").resolve()),
        "continuation_lineage": str((result_dir / "continuation_lineage.json").resolve()),
        "plots": plot_paths,
        "physical_identity": physical_identity,
        "developed_flow_sha256": developed_sha,
    }
    (result_dir / "flow_summary_v2.json").write_text(json.dumps(_json_safe(summary), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def _collect_continuation_forces(case: Path) -> tuple[list[ForceSample], list[Path]]:
    root = case / "postProcessing" / "cylinderForces"
    files = sorted(root.glob("*/forces.dat"), key=lambda path: float(path.parent.name))
    if not files:
        raise DevelopedFlowError(f"continuation force history is missing: {root}")
    from .developed_flow import parse_force_history

    by_time: dict[float, ForceSample] = {}
    for path in files:
        for sample in parse_force_history(path):
            key = round(sample.time_s, 9)
            if key in by_time and not _force_close(by_time[key], sample):
                raise DevelopedFlowError(f"continuation force timestamp conflict: {sample.time_s}")
            by_time[key] = sample
    samples = [by_time[key] for key in sorted(by_time)]
    _validate_force_times(samples, label=str(case))
    return samples, files


def resume_existing_v2_flow_case(*, flow_id: str, U: float, root: Path = V2_FLOW_ROOT, result_root: Path = V2_RESULT_ROOT) -> dict[str, Any]:
    """Recover artifacts after an interrupted v2 result-writing step.

    This function never starts a solver.  It is intentionally limited to an
    already-created v2 continuation case and reconstructs evaluations from
    the immutable source plus the real continuation force files/logs.
    """

    source_summary, source_case, source_csv = _read_source_summary(flow_id)
    target_case = root / flow_id
    result_dir = result_root / flow_id
    lineage_path = target_case / "continuation_lineage.json"
    if not target_case.is_dir() or not lineage_path.is_file():
        raise DevelopedFlowError(f"existing v2 continuation lineage is missing for {flow_id}")
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    if lineage.get("flow_id") != flow_id or not math.isclose(float(lineage.get("U_mps", -1.0)), float(U), rel_tol=0.0, abs_tol=1.0e-12):
        raise DevelopedFlowError("existing v2 lineage has the wrong Reynolds case")
    source_samples = read_force_csv(source_csv)
    continuation_samples, force_paths = _collect_continuation_forces(target_case)
    merged = merge_force_histories(source_samples, continuation_samples)
    _write_force_csv(result_dir / "force_history_merged.csv", merged["samples"])
    source_discard = float(source_summary.get("statistics", {}).get("discarded_startup_transient_s", 0.0))
    log_paths = sorted(target_case.glob("log.pimpleFoam_cont_*s"), key=lambda path: float(re.search(r"cont_([0-9.]+)s", path.name).group(1)))
    if not log_paths:
        raise DevelopedFlowError(f"no completed v2 continuation solver logs for {flow_id}")
    evaluations: list[dict[str, Any]] = []
    stable_consecutive = 0
    for log in log_paths:
        match = re.search(r"cont_([0-9.]+)s", log.name)
        if match is None:
            continue
        requested_end = float(match.group(1))
        prefix = [sample for sample in continuation_samples if sample.time_s <= requested_end + 0.01]
        prefix_merge = merge_force_histories(source_samples, prefix)
        stats = analyze_force_history_v2(prefix_merge["samples"], U=U, discard_start_s=source_discard)
        stable_consecutive = stable_consecutive + 1 if stats["all_stable_criteria"] else 0
        evaluations.append({"end_time_s": prefix_merge["last_time_s"], "requested_end_time_s": requested_end, "stable_consecutive": stable_consecutive, "statistics": stats})
    if not evaluations:
        raise DevelopedFlowError(f"no evaluable v2 continuation logs for {flow_id}")
    stats = evaluations[-1]["statistics"]
    continuation_end = float(merged["last_time_s"])
    continuation_hash = sha256_file(result_dir / "force_history_merged.csv")
    final_value, final_dir = max(
        ((float(child.name), child) for child in target_case.iterdir() if child.is_dir() and re.fullmatch(r"[0-9.eE+-]+", child.name)),
        key=lambda item: item[0],
    )
    required = [final_dir / name for name in ("U", "p", "phi", Path("uniform") / "time")]
    if not all(path.is_file() for path in required):
        raise DevelopedFlowError(f"existing v2 final fields are incomplete for {flow_id}")
    final_fields = {str(path.relative_to(target_case)).replace("\\", "/"): sha256_file(path) for path in required}
    check_log = target_case / "log.checkMesh_continuation"
    check = {"label": "checkMesh_continuation", "return_code": 0, "log": str(check_log.resolve()), "mesh_ok": check_log.is_file() and "Mesh OK" in check_log.read_text(encoding="utf-8", errors="replace")}
    max_cfl = max(float(source_summary.get("max_cfl", 0.0)), _cfl_from_logs(log_paths))
    lineage.update({
        "continuation_blocks": len(log_paths),
        "continuation_end_time_s": continuation_end,
        "continuation_force_sha256": continuation_hash,
        "continuation_sample_count": merged["continuation_sample_count"],
        "merged_sample_count": merged["merged_sample_count"],
        "merged_force_sha256": continuation_hash,
        "merged_force_file": str((result_dir / "force_history_merged.csv").resolve()),
        "source_force_sha256_after_run": sha256_file(source_csv),
        "source_force_unchanged": sha256_file(source_csv) == lineage["source_force_sha256"],
        "recovered_without_solver_restart": True,
    })
    lineage_path.write_text(json.dumps(_json_safe(lineage), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    convergence = {"status": "developed" if stats["all_stable_criteria"] and evaluations[-1]["stable_consecutive"] >= 3 else "blocked", "evaluation_count": len(evaluations), "required_consecutive_stable_points": 3, "evaluations": evaluations}
    (result_dir / "convergence_history.json").write_text(json.dumps(_json_safe(convergence), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    plot_paths = _plot_diagnostics(result_dir, merged["samples"], stats, U=U, rho=1000.0, D=1.0, span=1.0)
    physical_identity = {
        "flow_id": flow_id, "U_mps": U, "Re": U / 0.01, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "D_m": 1.0, "dt_s": DT_S,
        "source_final_fields": lineage["source_final_fields"], "source_force_sha256": lineage["source_force_sha256"], "merged_force_sha256": continuation_hash,
        "final_fields": final_fields, "end_time_s": continuation_end,
        "statistics": {"dominant_frequency_Hz": stats["dominant_frequency_Hz"], "zero_crossing_frequency_Hz": stats["zero_crossing_frequency_Hz"], "St": stats["St"], "mean_Cd": stats["window_2"].get("mean_Cd"), "Cl_rms": stats["window_2"].get("Cl_rms"), "criteria": stats["criteria"]},
    }
    summary = {
        "status": "developed" if convergence["status"] == "developed" else "blocked", "flow_id": flow_id, "U_mps": U, "Re": U / 0.01,
        "source_status": source_summary.get("status"), "total_runtime_s": continuation_end, "source_runtime_s": source_summary.get("end_time_s"),
        "continuation_runtime_s": continuation_end - float(source_summary.get("end_time_s", 0.0)), "statistics": stats, "max_cfl": max_cfl, "checkMesh": check,
        "solver_runs": [{"label": log.stem, "return_code": 0, "log": str(log.resolve())} for log in log_paths], "final_time_name": final_dir.name,
        "final_fields": final_fields, "force_history_merged_csv": str((result_dir / "force_history_merged.csv").resolve()), "merged_force_sha256": continuation_hash,
        "convergence_history": str((result_dir / "convergence_history.json").resolve()), "continuation_lineage": str((result_dir / "continuation_lineage.json").resolve()),
        "plots": plot_paths, "physical_identity": physical_identity, "developed_flow_sha256": canonical_sha(physical_identity),
        "recovered_without_solver_restart": True,
    }
    (result_dir / "flow_summary_v2.json").write_text(json.dumps(_json_safe(summary), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def build_developed_flow_bank_v2(*, root: Path = V2_FLOW_ROOT, result_root: Path = V2_RESULT_ROOT) -> dict[str, Any]:
    result_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for flow_id, U in (("re80", 0.8), ("re100", 1.0), ("re120", 1.2)):
        summary_path = result_root / flow_id / "flow_summary_v2.json"
        records.append(json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else run_v2_flow_case(flow_id=flow_id, U=U, root=root, result_root=result_root))
    bank_identity = [{"flow_id": item["flow_id"], "U_mps": item["U_mps"], "Re": item["Re"], "developed_flow_sha256": item["developed_flow_sha256"]} for item in records]
    bank = {
        "status": "ready_for_sol_review" if all(item["status"] == "developed" for item in records) else "blocked",
        "schema_version": "stage4d-developed-flow-bank-v2-1",
        "flow_ids": [item["flow_id"] for item in records],
        "flows": records,
        "developed_flow_bank_sha256": canonical_sha(bank_identity),
        "bank_identity_excludes_absolute_paths": True,
        "physical_time_limit_s": MAX_PHYSICAL_TIME_S,
        "created_utc": time.time(),
    }
    (result_root / "developed_flow_bank_v2.json").write_text(json.dumps(_json_safe(bank), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return bank


def audit_v2_flow_identity(summary: Mapping[str, Any], *, case: Path, result_dir: Path) -> dict[str, Any]:
    fields = dict(summary.get("final_fields", {}))
    if not fields:
        raise DevelopedFlowError("v2 summary has no final_fields")
    actual = {relative: sha256_file(case / relative) for relative in fields if (case / relative).is_file()}
    if actual != fields:
        raise DevelopedFlowError("v2 final field hash mismatch")
    force_path = Path(str(summary["force_history_merged_csv"]))
    if not force_path.is_file() or sha256_file(force_path) != summary["merged_force_sha256"]:
        raise DevelopedFlowError("v2 merged force hash mismatch")
    identity = dict(summary["physical_identity"])
    if canonical_sha(identity) != summary["developed_flow_sha256"]:
        raise DevelopedFlowError("v2 developed-flow identity hash mismatch")
    lineage = json.loads((result_dir / "continuation_lineage.json").read_text(encoding="utf-8"))
    if not lineage.get("source_force_unchanged") or lineage.get("setFields_called"):
        raise DevelopedFlowError("v2 continuation lineage is invalid")
    return {"status": "passed", "developed_flow_sha256": summary["developed_flow_sha256"], "field_count": len(fields), "force_sha256": summary["merged_force_sha256"]}
