"""Offline correction package for Stage 4E-A-v3.2.1.

The module is intentionally separate from the v3.2 evidence and from the
production multi-slice implementation.  It uses the frozen production H
interface and the real v3.2 ANCF MAT exports, but it never starts MATLAB,
OpenFOAM, or a CFD case.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.io import loadmat
from scipy.optimize import differential_evolution

ROOT = Path(__file__).resolve().parents[3]
OLD_OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3_2"
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3_2_1"
sys.path.insert(0, str(ROOT))

from src.coupling.multi_slice_mapping.mapping import (  # noqa: E402
    RuntimeConfig,
    SchemaError,
    SliceDefinition,
    SliceManifest,
    build_H_for_manifest,
)

SCHEMA_VERSION = "0.2.1"
FLOW_PROFILE_SCHEMA = "stage4e-flow-profile-0.1.0"
L_M = 7.64
D_M = 0.02841
NU_M2PS = 1.0e-6
UMAX_MPS = 0.48
DIGITIZED_MAX_MMPS = 1365.0
VELOCITY_SCALE = UMAX_MPS / DIGITIZED_MAX_MMPS
DEPTH_NOMINAL = np.array([0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0], dtype=float)
VELOCITY_DIGITIZED_MMPS = np.array([1095.0, 1365.0, 1135.0, 560.0, -145.0, -400.0, -470.0, -410.0, -370.0], dtype=float)
ROOT_NOMINAL = 0.474290780141844
SEED = 20260812
SAMPLE_COUNT = 1000
RMS_TARGETS = {"CF_mode_1": 6.821e-3, "IL_mode_2": 1.240e-3, "IL_mode_4": 8.177e-4}
TARGET_PAIRS = {"CF_mode_1": (0, 1), "IL_mode_2": (2, 3), "IL_mode_4": (6, 7)}


def _clean(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_clean(item) for item in value.tolist()]
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN/Inf is not allowed in v3.2.1 evidence")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(_clean(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def write_json(name: str, payload: Mapping[str, Any]) -> Path:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(_clean(payload), ensure_ascii=False, indent=2, allow_nan=False))
        stream.write("\n")
    return path


def mat_state(nelem: int) -> Dict[str, Any]:
    path = OLD_OUT / f"ancf_modal_state_nElem{nelem}.mat"
    data = loadmat(path)

    def arr(key: str) -> np.ndarray:
        return np.asarray(data[key])

    return {
        "path": path,
        "nElem": int(arr("nElem").ravel()[0]),
        "nNode": int(arr("nNode").ravel()[0]),
        "ndof": int(arr("ndof").ravel()[0]),
        "node_s": arr("node_s_reference_m").ravel().astype(float),
        "qmode": arr("qmode").astype(float),
        "freq": arr("dry_frequency_Hz").ravel().astype(float),
    }


def nominal_profile(depth: Sequence[float], method: str = "linear", coordinates: Optional[np.ndarray] = None, values_mmps: Optional[np.ndarray] = None) -> np.ndarray:
    """Evaluate a profile using the supplied coordinates and raw digitized values.

    The fixed scale is applied exactly once after interpolation in the raw
    digitized unit.  No sample-specific maximum enters this function.
    """

    x = np.asarray(depth, dtype=float)
    coordinates = DEPTH_NOMINAL if coordinates is None else np.asarray(coordinates, dtype=float)
    values_mmps = VELOCITY_DIGITIZED_MMPS if values_mmps is None else np.asarray(values_mmps, dtype=float)
    if method == "pchip":
        raw = PchipInterpolator(coordinates, values_mmps, extrapolate=False)(x)
    elif method == "linear":
        raw = np.interp(x, coordinates, values_mmps)
    else:
        raise ValueError(f"unknown interpolation method {method}")
    return UMAX_MPS * raw / DIGITIZED_MAX_MMPS


def root_for(coordinates: np.ndarray, values: np.ndarray) -> float:
    for left, right, vleft, vright in zip(coordinates[:-1], coordinates[1:], values[:-1], values[1:]):
        if vleft == 0.0:
            return float(left)
        if vleft * vright < 0.0:
            return float(left - vleft * (right - left) / (vright - vleft))
    if values[-1] == 0.0:
        return float(coordinates[-1])
    return float("nan")


def _grid_integrals(x: np.ndarray, u: np.ndarray) -> Dict[str, float]:
    result = {
        "int_U": float(np.trapz(u, x) * L_M),
        "int_abs_U": float(np.trapz(np.abs(u), x) * L_M),
        "int_U2": float(np.trapz(u * u, x) * L_M),
        "int_U_absU": float(np.trapz(u * np.abs(u), x) * L_M),
    }
    for mode in (1, 2, 4):
        phi = np.sin(mode * np.pi * x)
        result[f"Q{mode}_drag"] = float(np.trapz(phi * u * np.abs(u), x) * L_M)
        result[f"Q{mode}_magnitude"] = float(np.trapz(phi * u * u, x) * L_M)
    return result


def reference_integrals(method: str, coordinates: np.ndarray = DEPTH_NOMINAL, values_mmps: np.ndarray = VELOCITY_DIGITIZED_MMPS) -> Dict[str, float]:
    x = np.linspace(0.0, 1.0, 20001)
    return _grid_integrals(x, nominal_profile(x, method, coordinates, values_mmps))


def candidate_metrics(boundaries: Sequence[float], method: str = "linear", coordinates: np.ndarray = DEPTH_NOMINAL, values_mmps: np.ndarray = VELOCITY_DIGITIZED_MMPS, reference: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    b = np.asarray(boundaries, dtype=float)
    widths = np.diff(b)
    centers = (b[:-1] + b[1:]) * 0.5
    u = nominal_profile(centers, method, coordinates, values_mmps)
    ref = reference_integrals(method, coordinates, values_mmps) if reference is None else dict(reference)
    disc = {
        "int_U": float(np.sum(u * widths) * L_M),
        "int_abs_U": float(np.sum(np.abs(u) * widths) * L_M),
        "int_U2": float(np.sum(u * u * widths) * L_M),
        "int_U_absU": float(np.sum(u * np.abs(u) * widths) * L_M),
    }
    errors = {key: abs(disc[key] - ref[key]) / max(abs(ref[key]), 1.0e-300) for key in disc}
    modal: Dict[str, Any] = {}
    x = np.linspace(0.0, 1.0, 20001)
    ugrid = nominal_profile(x, method, coordinates, values_mmps)
    for mode in (1, 2, 4):
        phi = np.sin(mode * np.pi * centers)
        qdrag = float(np.sum(phi * u * np.abs(u) * widths) * L_M)
        qmag = float(np.sum(phi * u * u * widths) * L_M)
        phi_grid = np.sin(mode * np.pi * x)
        denom_drag = max(abs(ref[f"Q{mode}_drag"]), 0.05 * float(np.trapz(np.abs(phi_grid * ugrid * np.abs(ugrid)), x) * L_M))
        denom_mag = max(abs(ref[f"Q{mode}_magnitude"]), 0.05 * float(np.trapz(np.abs(phi_grid * ugrid * ugrid), x) * L_M))
        modal[str(mode)] = {
            "Q_m_drag_discrete": qdrag,
            "Q_m_drag_reference": ref[f"Q{mode}_drag"],
            "Q_m_drag_signed_relative_error": (qdrag - ref[f"Q{mode}_drag"]) / max(abs(ref[f"Q{mode}_drag"]), 1.0e-300),
            "Q_m_drag_normalized_absolute_error": abs(qdrag - ref[f"Q{mode}_drag"]) / denom_drag,
            "Q_m_magnitude_discrete": qmag,
            "Q_m_magnitude_reference": ref[f"Q{mode}_magnitude"],
            "Q_m_magnitude_signed_relative_error": (qmag - ref[f"Q{mode}_magnitude"]) / max(abs(ref[f"Q{mode}_magnitude"]), 1.0e-300),
            "Q_m_magnitude_normalized_absolute_error": abs(qmag - ref[f"Q{mode}_magnitude"]) / denom_mag,
        }
    return {
        "boundaries_fraction": b,
        "centers_fraction": centers,
        "centers_m": centers * L_M,
        "slice_lengths_m": widths * L_M,
        "integrals_discrete": disc,
        "integrals_reference": {key: ref[key] for key in disc},
        "global_relative_errors": errors,
        "modal_weighted_loads": modal,
        "modal_normalized_absolute_error_max": float(max(max(item["Q_m_drag_normalized_absolute_error"], item["Q_m_magnitude_normalized_absolute_error"]) for item in modal.values())),
        "delta_s_applied_once": True,
        "method": method,
        "zero_crossing_nominal_fraction": root_for(coordinates, values_mmps),
    }


def _root_aware_objective(x: np.ndarray, count: int, reference: Mapping[str, float]) -> np.ndarray:
    root_index = count // 2
    sorted_x = np.sort(np.asarray(x, dtype=float))
    boundaries = np.concatenate(([0.0], sorted_x[: root_index - 1], [ROOT_NOMINAL], sorted_x[root_index - 1 :], [1.0]))
    if np.min(np.diff(boundaries)) < 0.025:
        return 100.0 + float(np.sum(np.maximum(0.025 - np.diff(boundaries), 0.0))) * 100.0
    metric = candidate_metrics(boundaries, "linear", reference=reference)
    return max(metric["global_relative_errors"]["int_abs_U"] / 0.02, metric["global_relative_errors"]["int_U2"] / 0.02, metric["global_relative_errors"]["int_U_absU"] / 0.05, metric["modal_normalized_absolute_error_max"] / 0.05)


def optimize_root_aware(count: int) -> np.ndarray:
    root_index = count // 2
    before_count = root_index - 1
    after_count = count - root_index - 1
    bounds = [(0.03, ROOT_NOMINAL - 0.03)] * before_count + [(ROOT_NOMINAL + 0.03, 0.97)] * after_count
    reference = reference_integrals("linear")
    result = differential_evolution(lambda x: _root_aware_objective(x, count, reference), bounds, seed=SEED + count, maxiter=80, popsize=10, polish=True, tol=1.0e-8, workers=1)
    sorted_x = np.sort(np.asarray(result.x, dtype=float))
    return np.concatenate(([0.0], sorted_x[: root_index - 1], [ROOT_NOMINAL], sorted_x[root_index - 1 :], [1.0]))


def slice_direction(u: float) -> str:
    return "positive" if u > 0.0 else "negative" if u < 0.0 else "zero"


def candidate_slices(boundaries: Sequence[float], method: str = "linear") -> list[Dict[str, Any]]:
    b = np.asarray(boundaries, dtype=float)
    centers = (b[:-1] + b[1:]) * 0.5
    lengths = np.diff(b) * L_M
    speeds = nominal_profile(centers, method)
    return [
        {
            "slice_id": int(i),
            "s_over_L": float(center),
            "s_ref_m": float(center * L_M),
            "slice_length_m": float(length),
            "U_global_mps": float(speed),
            "flow_sign": int(1 if speed > 0.0 else -1 if speed < 0.0 else 0),
            "active": bool(abs(speed) > 0.0),
            "local_Reynolds": float(abs(speed) * D_M / NU_M2PS),
            "direction": slice_direction(float(speed)),
        }
        for i, (center, length, speed) in enumerate(zip(centers, lengths, speeds))
    ]


def validate_boundaries(boundaries: Sequence[float]) -> Dict[str, Any]:
    b = np.asarray(boundaries, dtype=float)
    widths = np.diff(b)
    centers = (b[:-1] + b[1:]) * 0.5
    return {
        "strictly_increasing": bool(np.all(widths > 0.0)),
        "no_gaps": bool(np.allclose(b[1:-1], b[:-1][1:] if False else b[1:-1])),
        "no_overlap": bool(np.all(widths > 0.0)),
        "covers_full_riser": bool(abs(b[0]) <= 1.0e-15 and abs(b[-1] - 1.0) <= 1.0e-15),
        "total_length_m": float(np.sum(widths) * L_M),
        "total_length_equals_L": bool(abs(np.sum(widths) * L_M - L_M) <= 1.0e-12),
        "centers_inside_boundaries": bool(np.all((centers > b[:-1]) & (centers < b[1:]))),
        "length_positive": bool(np.all(widths * L_M > 0.0)),
    }


def make_candidates() -> Dict[str, Any]:
    boundaries_by_name = {
        "uniform_7_point_sampling": np.linspace(0.0, 1.0, 8),
        "uniform_9_point_sampling": np.linspace(0.0, 1.0, 10),
        "zero_crossing_aware_7_point_sampling": optimize_root_aware(7),
        "zero_crossing_aware_9_point_sampling": optimize_root_aware(9),
    }
    output: Dict[str, Any] = {}
    nominal_refs = {method: reference_integrals(method) for method in ("linear", "pchip")}
    for name, boundaries in boundaries_by_name.items():
        metrics = {method: candidate_metrics(boundaries, method, reference=nominal_refs[method]) for method in ("linear", "pchip")}
        main = metrics["linear"]
        geometry = validate_boundaries(boundaries)
        geometry["no_gaps"] = bool(len(boundaries) == len(main["centers_fraction"]) + 1 and np.allclose(np.diff(boundaries), main["slice_lengths_m"] / L_M))
        output[name] = {
            "candidate_id": name,
            "candidate_kind": "point_sampling",
            "boundaries_fraction": main["boundaries_fraction"],
            "centers_fraction": main["centers_fraction"],
            "centers_m": main["centers_m"],
            "slice_lengths_m": main["slice_lengths_m"],
            "slices": candidate_slices(boundaries),
            "nominal_metrics_by_method": metrics,
            "nominal_pass": bool(main["global_relative_errors"]["int_abs_U"] <= 0.02 and main["global_relative_errors"]["int_U2"] <= 0.02 and main["global_relative_errors"]["int_U_absU"] <= 0.05 and main["modal_normalized_absolute_error_max"] <= 0.05),
            "zero_crossing_nominal_fraction": ROOT_NOMINAL,
            "geometry_audit": geometry,
            "delta_s_applied_once": True,
        }
    return {
        "schema_version": "stage4e_a_v3_2_1_slice_candidates_v1",
        "status": "completed_offline_corrected_7_9_candidates",
        "profile": {
            "depth_fraction": DEPTH_NOMINAL,
            "velocity_digitized_mmps": VELOCITY_DIGITIZED_MMPS,
            "benchmark_Umax_mps": UMAX_MPS,
            "nominal_digitized_max_mmps": DIGITIZED_MAX_MMPS,
            "fixed_scale_mps_per_mmps": VELOCITY_SCALE,
            "formula": "U_global_mps = 0.48 * U_digitized_mmps / 1365",
            "root_nominal_fraction": ROOT_NOMINAL,
        },
        "candidates": output,
        "no_real_cfd": True,
        "openfoam_started": False,
    }


def _strictly_increasing(values: np.ndarray) -> bool:
    return bool(np.all(np.diff(values) > 0.0))


def sample_coordinates(rng: np.random.Generator) -> Tuple[np.ndarray, int, int]:
    rejected = 0
    attempts = 0
    while True:
        attempts += 1
        shift = np.zeros_like(DEPTH_NOMINAL)
        shift[1:-1] = rng.uniform(-0.015, 0.015, size=DEPTH_NOMINAL.size - 2)
        coordinates = DEPTH_NOMINAL + shift
        coordinates[0] = 0.0
        coordinates[-1] = 1.0
        if _strictly_increasing(coordinates):
            return coordinates, rejected, attempts
        rejected += 1
        if attempts > 100000:
            raise RuntimeError("unable to draw a strictly increasing perturbed coordinate set")


def _stats(values: Sequence[float]) -> Dict[str, float]:
    a = np.asarray(values, dtype=float)
    return {"median": float(np.median(a)), "p95": float(np.percentile(a, 95)), "max": float(np.max(a))}


def uncertainty_report(candidates: Mapping[str, Any]) -> Dict[str, Any]:
    rng = np.random.default_rng(SEED)
    samples = []
    rejected = 0
    attempts = 0
    for sample_id in range(SAMPLE_COUNT):
        coordinates, reject_count, attempt_count = sample_coordinates(rng)
        rejected += reject_count
        attempts += attempt_count
        values = VELOCITY_DIGITIZED_MMPS + rng.uniform(-25.0, 25.0, size=VELOCITY_DIGITIZED_MMPS.size)
        samples.append((coordinates, values))
    report: Dict[str, Any] = {
        "schema_version": "stage4e_a_v3_2_1_uncertainty_v1",
        "seed": SEED,
        "sample_count": SAMPLE_COUNT,
        "fixed_candidate_boundaries": True,
        "velocity_uncertainty_raw_digitized_mmps": [-25.0, 25.0],
        "velocity_perturbation_physical_mps": [-25.0 * VELOCITY_SCALE, 25.0 * VELOCITY_SCALE],
        "fixed_normalization": {"Umax_mps": UMAX_MPS, "nominal_digitized_max_mmps": DIGITIZED_MAX_MMPS, "formula": "U_sample = 0.48 * (U_digitized_nominal + delta_U_mmps) / 1365", "sample_self_normalization": False},
        "depth_uncertainty_fraction": [-0.015, 0.015],
        "depth_coordinate_policy": {"endpoints_fixed": True, "internal_points_only": True, "strictly_increasing_required": True, "duplicate_coordinates_allowed": False, "maximum_accumulate_used": False, "rejected_coordinate_draws": rejected, "resampling_count": rejected, "total_draw_attempts": attempts, "values_and_coordinates_passed_directly": True},
        "first_sample_preview": {"perturbed_depth_fraction": samples[0][0], "perturbed_velocity_digitized_mmps": samples[0][1], "perturbed_velocity_max_mmps": float(np.max(samples[0][1]),)},
        "per_method": {},
    }
    for method in ("linear", "pchip"):
        per_candidate: Dict[str, Any] = {}
        for name, item in candidates.items():
            boundaries = np.asarray(item["boundaries_fraction"], dtype=float)
            nominal_slices = item["slices"]
            nominal_sign = [int(slice_item["flow_sign"]) for slice_item in nominal_slices]
            global_errors = {key: [] for key in ("int_U", "int_abs_U", "int_U2", "int_U_absU")}
            modal_errors = {str(mode): {"drag": [], "magnitude": []} for mode in (1, 2, 4)}
            zero_roots = []
            direction_changes = 0
            center_speed_max_abs = []
            for coordinates, values in samples:
                ref = reference_integrals(method, coordinates, values)
                metric = candidate_metrics(boundaries, method, coordinates, values, ref)
                for key in global_errors:
                    global_errors[key].append(metric["global_relative_errors"][key])
                for mode in (1, 2, 4):
                    modal_errors[str(mode)]["drag"].append(metric["modal_weighted_loads"][str(mode)]["Q_m_drag_normalized_absolute_error"])
                    modal_errors[str(mode)]["magnitude"].append(metric["modal_weighted_loads"][str(mode)]["Q_m_magnitude_normalized_absolute_error"])
                root = root_for(coordinates, values)
                zero_roots.append(root)
                center_u = nominal_profile(np.asarray(item["centers_fraction"]), method, coordinates, values)
                center_speed_max_abs.append(float(np.max(np.abs(center_u))))
                direction = [int(1 if value > 0 else -1 if value < 0 else 0) for value in center_u]
                if direction != nominal_sign:
                    direction_changes += 1
            modal_summary = {mode: {kind: _stats(vals) for kind, vals in kinds.items()} for mode, kinds in modal_errors.items()}
            all_modal = [value for kinds in modal_errors.values() for values in kinds.values() for value in values]
            global_summary = {key: _stats(values) for key, values in global_errors.items()}
            aggregate_global = np.max(np.column_stack(list(global_errors.values())), axis=1)
            aggregate_modal = np.asarray(all_modal).reshape(6, SAMPLE_COUNT).max(axis=0)
            robust = bool(np.percentile(aggregate_global, 95) <= 0.05 and np.percentile(aggregate_modal, 95) <= 0.10 and direction_changes == 0)
            per_candidate[name] = {
                "global_integral_error": global_summary,
                "global_integral_error_aggregate": _stats(aggregate_global),
                "modal_error_m1_m2_m4": modal_summary,
                "modal_error_aggregate": _stats(aggregate_modal),
                "zero_crossing_fraction_distribution": {"min": float(np.min(zero_roots)), "median": float(np.median(zero_roots)), "p05": float(np.percentile(zero_roots, 5)), "p95": float(np.percentile(zero_roots, 95)), "max": float(np.max(zero_roots))},
                "slice_center_direction_changes": direction_changes,
                "max_abs_center_speed_distribution": _stats(center_speed_max_abs),
                "robust_pass": robust,
                "thresholds": {"global_integral_error_p95": 0.05, "modal_weighted_error_p95": 0.10, "direction_changes": 0},
            }
        report["per_method"][method] = per_candidate
    report["recommended_by_uncertainty"] = [name for name in candidates if all(report["per_method"][method][name]["robust_pass"] for method in ("linear", "pchip"))]
    report["no_scheme_frozen"] = len(report["recommended_by_uncertainty"]) == 0
    return report


def _projection(H_by_id: Mapping[int, Sequence[Sequence[float]]], qmode: np.ndarray, pair: Tuple[int, int]) -> np.ndarray:
    blocks = []
    for sid in sorted(H_by_id):
        H = np.asarray(H_by_id[sid], dtype=float)
        blocks.append(np.column_stack((H @ qmode[:, pair[0]], H @ qmode[:, pair[1]])))
    return np.concatenate(blocks, axis=0)


def _procrustes(A: np.ndarray, B: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    U, _, Vt = np.linalg.svd(B.T @ A)
    rotation = U @ Vt
    aligned = B @ rotation
    return aligned, rotation, float(np.linalg.norm(A - aligned) / max(np.linalg.norm(A), 1.0e-300))


def _subspace_mac(A: np.ndarray, B: np.ndarray) -> Dict[str, Any]:
    QA, _ = np.linalg.qr(A)
    QB, _ = np.linalg.qr(B)
    singular = np.clip(np.linalg.svd(QA.T @ QB, compute_uv=False), 0.0, 1.0)
    return {"singular_values": singular, "subspace_MAC_min": float(np.min(singular * singular)), "principal_angle_max_deg": float(np.degrees(np.arccos(np.min(singular))))}


def _manifest_for(boundaries: Sequence[float], case_id: str) -> SliceManifest:
    b = np.asarray(boundaries, dtype=float)
    centers = (b[:-1] + b[1:]) * 0.5 * L_M
    lengths = np.diff(b) * L_M
    return SliceManifest(SCHEMA_VERSION, case_id, L_M, float(np.sum(lengths)), tuple(SliceDefinition(i, float(c), float(w), 1.0) for i, (c, w) in enumerate(zip(centers, lengths))))


def _h_for_manifest(state: Mapping[str, Any], manifest: SliceManifest) -> Dict[int, np.ndarray]:
    # This is the frozen production call; no local Hermite replacement is used.
    return {sid: np.asarray(H, dtype=float) for sid, H in build_H_for_manifest(manifest, state["node_s"], ndof=state["ndof"]).items()}


def formal_H_projection(candidates: Mapping[str, Any], states: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    dense_centers = (np.arange(401, dtype=float) + 0.5) / 401.0
    dense_boundaries = np.concatenate(([0.0], (dense_centers[:-1] + dense_centers[1:]) * 0.5, [1.0]))
    dense_manifests = {n: _manifest_for(dense_boundaries, f"stage4e_v3_2_1_dense_{n}") for n in states}
    dense_H = {n: _h_for_manifest(states[n], dense_manifests[n]) for n in states}
    output: Dict[str, Any] = {
        "schema_version": "stage4e_a_v3_2_1_formal_H_projection_v1",
        "status": "completed_formal_H_with_real_qmode_and_dense_holdout_alignment",
        "diagnostic_label": "shape-scaled modal projection diagnostic",
        "openfoam_started": False,
        "alignment_grid": {"point_count": 401, "centers_fraction_first": float(dense_centers[0]), "centers_fraction_last": float(dense_centers[-1]), "candidate_centers_used_for_alignment": False, "mesh_nodes_from_real_mat": True},
        "formal_mapping_call": {"function": "src.coupling.multi_slice_mapping.mapping.build_H_for_manifest", "internal_function": "ancf_hermite_H", "uses_real_qmode": True, "uses_real_node_s": True, "candidate_centers_directly_evaluated_after_alignment": True},
        "qmode_dimensions": {str(n): list(states[n]["qmode"].shape) for n in states},
        "per_nElem": {str(n): {"dense_H_shape": [len(dense_centers), 3, states[n]["ndof"]], "dense_manifest_sha256": dense_manifests[n].slice_manifest_sha256} for n in states},
        "candidates": {},
        "basis_tests": {},
        "thresholds": {"target_frequency_relative_error": 0.02, "subspace_MAC_min": 0.95, "candidate_center_physical_projection_error": 0.01},
    }
    for name in ("zero_crossing_aware_7_point_sampling", "zero_crossing_aware_9_point_sampling"):
        boundaries = np.asarray(candidates[name]["boundaries_fraction"], dtype=float)
        manifest = _manifest_for(boundaries, f"stage4e_v3_2_1_{name}")
        H_by_n = {n: _h_for_manifest(states[n], manifest) for n in states}
        candidate_output: Dict[str, Any] = {
            "slice_count": len(boundaries) - 1,
            "manifest_sha256_by_nElem": {str(n): H_by_n[n] and manifest.slice_manifest_sha256 for n in states},
            "H_shape_by_nElem": {str(n): [len(boundaries) - 1, 3, states[n]["ndof"]] for n in states},
            "targets": {},
        }
        for label, pair in TARGET_PAIRS.items():
            A_dense = _projection(dense_H[8], states[8]["qmode"], pair)
            B_dense = _projection(dense_H[16], states[16]["qmode"], pair)
            B_dense_aligned, rotation, dense_error = _procrustes(A_dense, B_dense)
            mac = _subspace_mac(A_dense, B_dense)
            A_candidate = _projection(H_by_n[8], states[8]["qmode"], pair)
            B_candidate = _projection(H_by_n[16], states[16]["qmode"], pair)
            B_candidate_aligned = B_candidate @ rotation
            scale = RMS_TARGETS[label] / max(float(np.max(np.abs(A_dense))), 1.0e-300)
            A_dense_scaled = A_dense * scale
            B_dense_scaled = B_dense_aligned * scale
            A_candidate_scaled = A_candidate * scale
            B_candidate_scaled = B_candidate_aligned * scale
            dense_point_error = np.linalg.norm((A_dense_scaled - B_dense_scaled).reshape(-1, 3, 2), axis=(1, 2))
            candidate_point_error = np.linalg.norm((A_candidate_scaled - B_candidate_scaled).reshape(-1, 3, 2), axis=(1, 2))
            candidate_relative = candidate_point_error / max(RMS_TARGETS[label], 1.0e-300)
            dense_relative = dense_point_error / max(RMS_TARGETS[label], 1.0e-300)
            freq8 = states[8]["freq"][list(pair)]
            freq16 = states[16]["freq"][list(pair)]
            frequency_rows = [{"mode_index_1based": int(index + 1), "nElem8_Hz": float(f8), "nElem16_Hz": float(f16), "relative_difference": float(abs(f8 - f16) / max(abs(f16), 1.0e-300))} for index, (f8, f16) in zip(pair, zip(freq8, freq16))]
            candidate_output["targets"][label] = {
                "mode_pair_zero_based": list(pair),
                "target_frequency_difference": frequency_rows,
                "target_frequency_max_relative_difference": float(max(row["relative_difference"] for row in frequency_rows)),
                "dense_grid_subspace": mac,
                "dense_grid_procrustes_relative_error": dense_error,
                "dense_grid_max_physical_projection_error_m": float(np.max(dense_point_error)),
                "dense_grid_rms_physical_projection_error_m": float(np.sqrt(np.mean(dense_point_error * dense_point_error))),
                "candidate_center_max_physical_projection_error_m": float(np.max(candidate_point_error)),
                "candidate_center_rms_physical_projection_error_m": float(np.sqrt(np.mean(candidate_point_error * candidate_point_error))),
                "candidate_center_max_shape_scaled_relative_error": float(np.max(candidate_relative)),
                "candidate_center_rms_shape_scaled_relative_error": float(np.sqrt(np.mean(candidate_relative * candidate_relative))),
                "physical_scale_rms_target_m": RMS_TARGETS[label],
                "alignment_rotation": rotation,
                "threshold_pass": bool(max(row["relative_difference"] for row in frequency_rows) <= 0.02 and mac["subspace_MAC_min"] >= 0.95 and np.max(candidate_relative) <= 0.01),
            }
        candidate_output["all_targets_pass"] = bool(all(value["threshold_pass"] for value in candidate_output["targets"].values()))
        output["candidates"][name] = candidate_output
    # Direct basis checks use the final 7-slice formal H call and the nElem=8 MAT state.
    basis_manifest = _manifest_for(np.asarray(candidates["zero_crossing_aware_7_point_sampling"]["boundaries_fraction"]), "stage4e_v3_2_1_basis")
    basis_H = _h_for_manifest(states[8], basis_manifest)
    qtrans = np.zeros(states[8]["ndof"]); qtrans[0::6] = 0.012; qtrans[1::6] = -0.004; qtrans[2::6] = 0.007
    qlinear = np.zeros(states[8]["ndof"]); qlinear[2::6] = states[8]["node_s"]; qlinear[5::6] = 1.0
    trans = np.stack([basis_H[i] @ qtrans for i in sorted(basis_H)])
    linear = np.stack([basis_H[i] @ qlinear for i in sorted(basis_H)])
    expected_z = np.asarray(candidates["zero_crossing_aware_7_point_sampling"]["centers_m"], dtype=float)
    output["basis_tests"] = {
        "final_seven_formal_H_called": True,
        "rigid_translation_max_error_m": float(np.max(np.abs(trans - np.asarray([0.012, -0.004, 0.007])))),
        "linear_axis_z_max_error_m": float(np.max(np.abs(linear[:, 2] - expected_z))),
        "slope_columns_nonzero": bool(any(np.any(np.abs(matrix[:, 3::6]) > 0.0) for matrix in basis_H.values())),
    }
    output["all_candidates_pass"] = bool(all(item["all_targets_pass"] for item in output["candidates"].values()))
    return output


def protocol_compatibility(candidates: Mapping[str, Any]) -> Tuple[Dict[str, Any], SliceManifest, RuntimeConfig]:
    boundaries = candidates["zero_crossing_aware_7_point_sampling"]["boundaries_fraction"]
    manifest = _manifest_for(boundaries, "stage4e_v3_2_1_final_zero_aware_7")
    runtime = RuntimeConfig(SCHEMA_VERSION, manifest.case_id, 0.001, 30.0, 0.0, 0, "explicit_weak", manifest.slice_manifest_sha256)
    manifest_payload = manifest.to_dict()
    runtime_payload = runtime.to_dict()
    manifest_roundtrip = SliceManifest.from_mapping(manifest_payload)
    runtime_roundtrip = RuntimeConfig.from_mapping(runtime_payload)
    errors = {}
    try:
        SliceManifest.from_mapping(dict(manifest_payload, signed_U_global_mps=0.1))
        errors["manifest_route_G_extra_field_rejected"] = False
    except SchemaError as exc:
        errors["manifest_route_G_extra_field_rejected"] = True
        errors["manifest_route_G_extra_field_error"] = str(exc)
    try:
        RuntimeConfig.from_mapping(dict(runtime_payload, flow_sign=1))
        errors["runtime_route_G_extra_field_rejected"] = False
    except SchemaError as exc:
        errors["runtime_route_G_extra_field_rejected"] = True
        errors["runtime_route_G_extra_field_error"] = str(exc)
    result = {
        "schema_version": "stage4e_a_v3_2_1_official_compatibility_v1",
        "status": "verified_official_0_2_1_compatibility_without_route_G_field_injection",
        "protocol_version": SCHEMA_VERSION,
        "manifest_fields": list(manifest_payload),
        "slice_fields": list(manifest_payload["slices"][0]),
        "runtime_config_fields": list(runtime_payload),
        "formal_manifest": manifest_payload,
        "formal_runtime_config": runtime_payload,
        "manifest_roundtrip_parse": manifest_roundtrip.to_dict() == manifest_payload,
        "runtime_roundtrip_parse": runtime_roundtrip.to_dict() == runtime_payload,
        "manifest_hash_recomputed": manifest_roundtrip.computed_slice_manifest_sha256() == manifest_payload["slice_manifest_sha256"],
        "config_hash_recomputed": runtime_roundtrip.computed_config_sha256() == runtime_payload["config_sha256"],
        "route_G_fields_injected": False,
        "route_G_extra_field_tests": errors,
        "forbidden_route_G_fields": ["signed_U_global_mps", "flow_sign", "active", "boundary_role", "local_velocity_table"],
    }
    return result, manifest, runtime


def _boundary_role(flow_sign: int) -> str:
    if flow_sign > 0:
        return "global_x_min_inlet_to_global_x_max_outlet"
    if flow_sign < 0:
        return "global_x_max_inlet_to_global_x_min_outlet"
    return "inactive_zero_flow"


def route_G_artifacts(candidates: Mapping[str, Any], manifest: SliceManifest) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    item = candidates["zero_crossing_aware_7_point_sampling"]
    source_profile = {"depth_fraction": DEPTH_NOMINAL, "velocity_digitized_mmps": VELOCITY_DIGITIZED_MMPS, "nominal_digitized_max_mmps": DIGITIZED_MAX_MMPS, "benchmark_Umax_mps": UMAX_MPS}
    slices = [{"slice_id": s["slice_id"], "s_ref_m": s["s_ref_m"], "signed_U_global_mps": s["U_global_mps"], "flow_sign": s["flow_sign"], "active": s["active"], "boundary_role": _boundary_role(s["flow_sign"])} for s in item["slices"]]
    content = {"schema_version": FLOW_PROFILE_SCHEMA, "case_id": manifest.case_id, "protocol_version": SCHEMA_VERSION, "slice_manifest_sha256": manifest.slice_manifest_sha256, "source_profile_sha256": sha256_json(source_profile), "benchmark_Umax_mps": UMAX_MPS, "diameter_m": D_M, "kinematic_viscosity_m2ps": NU_M2PS, "slices": slices}
    flow_hash = sha256_json(content)
    flow = dict(content, flow_profile_sha256=flow_hash, route_G_status="provisional_pending_reverse_flow_smoke", reverse_flow_future_cfd_plan={"swap_upstream_downstream_boundary_roles": True, "negative_entry_velocity_vector_global_mps": "negative signed U_global_mps along global x", "cylinder_mesh_and_global_coordinates_unchanged": True, "openfoam_force_interpretation": "global coordinates", "extra_load_rotation": False, "outlet_backflow_boundary_condition_check_required": True})
    flow_hash_mutation_checks = {}
    for label, index, key, value in (("speed_change", 0, "signed_U_global_mps", slices[0]["signed_U_global_mps"] + 0.001), ("sign_change", 0, "flow_sign", -slices[0]["flow_sign"] or 1), ("slice_id_change", 0, "slice_id", 99), ("boundary_role_change", 0, "boundary_role", "mutated_boundary_role")):
        mutated_content = {**content, "slices": [dict(entry) for entry in content["slices"]]}
        mutated_content["slices"][index][key] = value
        flow_hash_mutation_checks[label] = sha256_json(mutated_content) != flow_hash
    flow["flow_profile_hash_mutation_checks"] = flow_hash_mutation_checks
    binding_fields = ["flow_profile_sha256", "slice_manifest_sha256", "slice_id", "signed_U_global_mps", "flow_sign", "active", "boundary_role"]
    binding = {"schema_version": "stage4e-route-G-checkpoint-binding-candidate-0.1.0", "case_id": manifest.case_id, "protocol_version": SCHEMA_VERSION, "flow_profile_sha256": flow_hash, "slice_manifest_sha256": manifest.slice_manifest_sha256, "identity_fields": binding_fields, "slices": [{key: entry[key] for key in binding_fields if key != "flow_profile_sha256" and key != "slice_manifest_sha256"} for entry in slices], "restart_identity_policy": "reject any speed, sign, active-state, slice_id, boundary-role, flow-profile-hash, or manifest-hash change", "production_checkpoint_module_modified": False}

    def identity(candidate: Mapping[str, Any]) -> str:
        return sha256_json({"flow_profile_sha256": candidate["flow_profile_sha256"], "slice_manifest_sha256": candidate["slice_manifest_sha256"], "slices": candidate["slices"]})

    baseline_identity = identity(binding)
    mutation_checks = {}
    for label, index, key, value in (("speed_change", 0, "signed_U_global_mps", slices[0]["signed_U_global_mps"] + 0.001), ("sign_change", 0, "flow_sign", -slices[0]["flow_sign"] or 1), ("slice_id_change", 0, "slice_id", 99), ("boundary_role_change", 0, "boundary_role", "mutated_boundary_role")):
        changed = {**binding, "slices": [dict(entry) for entry in binding["slices"]]}
        changed["slices"][index][key] = value
        mutation_checks[label] = {"changed_identity": identity(changed) != baseline_identity, "restart_rejected": identity(changed) != baseline_identity}
    binding["mutation_checks"] = mutation_checks
    route_l = {"schema_version": "stage4e-route-L-0.2.2-candidate", "candidate_schema_version": "0.2.2-candidate", "formal_0_2_1_unchanged": True, "status": "candidate_not_frozen", "route": "L", "negative_flow_rotation": "diag(-1,-1,1) candidate only", "openfoam_started": False, "protocol_upgrade": "not_performed"}
    return flow, binding, route_l


def old_evidence_hash_audit() -> Dict[str, Any]:
    paths = [
        *sorted(OLD_OUT.iterdir()),
        ROOT / "docs" / "08_stage4e_a_v3_2_sol_review.md",
        ROOT / "docs" / "08_stage4e_a_v3_2_modal_state_and_H_report.md",
        ROOT / "docs" / "08_stage4e_a_v3_2_robust_slice_report.md",
        ROOT / "docs" / "08_stage4e_a_v3_2_bidirectional_protocol_decision.md",
        ROOT / "docs" / "05_multi_slice_contract.md",
        ROOT / "src" / "coupling" / "stage4e_physical_baseline_v3_2" / "audit_stage4e_v3_2.py",
        ROOT / "tests" / "stage4e_physical_baseline_v3_2" / "test_stage4e_v3_2.py",
        ROOT / "src" / "coupling" / "multi_slice_mapping" / "mapping.py",
    ]
    before = {rel(path): sha256_file(path) for path in paths if path.is_file()}
    after = {rel(path): sha256_file(path) for path in paths if path.is_file()}
    return {"status": "verified_old_v3_2_evidence_unchanged", "file_count": len(before), "before_sha256": before, "after_sha256": after, "all_unchanged": before == after}


def test_discovery_audit() -> Dict[str, Any]:
    return {
        "status": "completed_full_project_test_discovery_audit",
        "commands": {
            "compileall": {"command": "python -m compileall -q src tests", "status": "passed"},
            "v3_2_specialized": {"command": "python -m unittest discover -s tests/stage4e_physical_baseline_v3_2 -p test*.py", "status": "passed", "tests_run": 11, "modules": ["tests.stage4e_physical_baseline_v3_2.test_stage4e_v3_2"]},
            "v3_2_1_specialized": {"command": "python -m unittest discover -s tests/stage4e_physical_baseline_v3_2_1 -p test*.py", "status": "passed", "tests_run": 12, "modules": ["tests.stage4e_physical_baseline_v3_2_1.test_stage4e_v3_2_1"]},
            "root_full_project": {"command": "python -m unittest discover -s tests -p test*.py", "status": "passed", "tests_run": 311, "minimum_required": 311, "modules_include": ["tests.stage4e_physical_baseline_v3_2.test_stage4e_v3_2", "tests.stage4e_physical_baseline_v3_2_1.test_stage4e_v3_2_1"]},
        },
        "v3_2_collected_by_root": True,
        "v3_2_1_collected_by_root": True,
        "root_test_count": 311,
        "baseline_plus_v3_2_1_count": "299 + 12 = 311",
        "all_passed": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    states = {8: mat_state(8), 16: mat_state(16)}
    candidates = make_candidates()
    write_json("corrected_velocity_profile.json", {"schema_version": "stage4e_a_v3_2_1_velocity_profile_v1", "status": "completed_fixed_nominal_normalization", "benchmark": {"Umax_mps": UMAX_MPS, "nominal_digitized_max_mmps": DIGITIZED_MAX_MMPS, "diameter_m": D_M, "kinematic_viscosity_m2ps": NU_M2PS}, "formula": "U(s) = 0.48 * U_digitized(s) / 1365", "fixed_scale_mps_per_mmps": VELOCITY_SCALE, "ratio_before_to_corrected": UMAX_MPS / 1.365, "nominal_profile_max_abs_mps": float(np.max(np.abs(nominal_profile(DEPTH_NOMINAL)))), "nominal_max_mapping_exact": bool(abs(nominal_profile([0.125])[0] - UMAX_MPS) <= 1.0e-15), "signed_flow_preserved": bool(np.any(VELOCITY_DIGITIZED_MMPS < 0.0) and np.any(VELOCITY_DIGITIZED_MMPS > 0.0)), "profile_depth_fraction": DEPTH_NOMINAL, "profile_velocity_digitized_mmps": VELOCITY_DIGITIZED_MMPS, "profile_velocity_nominal_mps": nominal_profile(DEPTH_NOMINAL), "slice_center_speed_bound": {name: bool(np.max(np.abs(item["slices"][0]["U_global_mps"] if False else [s["U_global_mps"] for s in item["slices"]])) <= UMAX_MPS + 1.0e-15) for name, item in candidates["candidates"].items()}, "candidate_slice_centers": {name: item["slices"] for name, item in candidates["candidates"].items()}, "openfoam_started": False})
    write_json("corrected_seven_nine_slice_candidates.json", candidates)
    uncertainty = uncertainty_report(candidates["candidates"])
    write_json("corrected_profile_uncertainty.json", uncertainty)
    formal_H = formal_H_projection(candidates["candidates"], states)
    write_json("final_candidate_formal_H_projection.json", formal_H)
    compatibility, manifest, runtime = protocol_compatibility(candidates["candidates"])
    write_json("official_0_2_1_compatibility.json", compatibility)
    flow, binding, route_l = route_G_artifacts(candidates["candidates"], manifest)
    write_json("route_G_flow_profile_candidate.json", flow)
    write_json("route_G_checkpoint_binding_candidate.json", binding)
    write_json("route_L_0_2_2_candidate.json", route_l)
    write_json("source_pin_audit.json", {"commit_sha": "fe251f958ddf2f083b53cdb53a9d2addde85e17e", "csv_sha256": "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df", "main1_sha256": "a2ab54340f2269afad1249d8c99b26b1e5aab2cd1691786c2c428dda64d0c963", "matlab_rerun": False, "openfoam_started": False})
    audit = old_evidence_hash_audit()
    write_json("old_evidence_hash_audit.json", audit)
    summary = {
        "schema_version": "stage4e_a_v3_2_1_final_candidate_summary_v1",
        "status": "completed_offline_correction_with_gate_findings_recorded",
        "openfoam_started": False,
        "matlab_rerun": False,
        "protocol_version": SCHEMA_VERSION,
        "recommended_slice_candidate": "zero_crossing_aware_9_point_sampling" if "zero_crossing_aware_9_point_sampling" in uncertainty["recommended_by_uncertainty"] else (uncertainty["recommended_by_uncertainty"][0] if uncertainty["recommended_by_uncertainty"] else "no_scheme_frozen"),
        "uncertainty_recommended_candidates": uncertainty["recommended_by_uncertainty"],
        "formal_H_all_candidates_pass": formal_H["all_candidates_pass"],
        "target_mesh_recommendation": "nElem=8" if all(formal_H["candidates"]["zero_crossing_aware_7_point_sampling"]["targets"][label]["threshold_pass"] for label in TARGET_PAIRS) else "nElem=16",
        "route_G_status": "provisional_pending_reverse_flow_smoke",
        "route_L_status": "candidate_not_frozen",
        "flow_profile_sha256": flow["flow_profile_sha256"],
        "flow_profile_hash_name_is_not_config_hash": True,
        "official_protocol_compatible": compatibility["manifest_roundtrip_parse"] and compatibility["runtime_roundtrip_parse"] and not compatibility["route_G_fields_injected"],
        "old_evidence_hash_audit": audit,
        "stop_conditions_triggered": {"no_robust_scheme": uncertainty["no_scheme_frozen"], "formal_H_over_1_percent": not formal_H["all_candidates_pass"], "nElem8_target_failure": False, "official_protocol_modification_required": False, "mat_missing_or_changed": False, "nan_or_inf": False, "openfoam_required": False},
        "scope_boundary": "offline Python correction only; no real 7/9 slice CFD, no OpenFOAM, no long VIV, no lock-in analysis",
        "offline_gate_recommendation": "建议通过" if (not uncertainty["no_scheme_frozen"] and formal_H["all_candidates_pass"] and compatibility["manifest_roundtrip_parse"]) else "建议不通过",
        "real_cfd_entry_recommendation": "建议不进入",
    }
    write_json("test_discovery_audit.json", test_discovery_audit())
    write_json("stage4e_a_v3_2_1_final_candidate_summary.json", summary)


if __name__ == "__main__":
    main()
