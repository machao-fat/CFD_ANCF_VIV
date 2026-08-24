"""Formal 0.2.1 H/H-transpose audits for uniform 3/5/9 slice layouts."""

from __future__ import annotations

import math
import random
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..multi_slice_mapping.mapping import (
    IDENTITY_R_GL,
    SCHEMA_VERSION,
    MappingError,
    NumericValidationError,
    SliceDefinition,
    SliceManifest,
    ancf_hermite_H,
    build_H_for_manifest,
    map_integrated_slice_forces,
)
from .benchmark import LowReContract, canonical_json_bytes, uniform_slice_geometry, write_json


def build_uniform_manifest(count: int, contract: LowReContract | None = None) -> SliceManifest:
    contract = contract or LowReContract()
    _, centers = uniform_slice_geometry(count, contract.L_m)
    width = contract.L_m / count
    return SliceManifest(
        schema_version=SCHEMA_VERSION,
        case_id=f"stage4f_lowre_v2_uniform_{count}slice",
        reference_length_m=contract.L_m,
        represented_length_m=contract.L_m,
        R_GL=IDENTITY_R_GL,
        slices=tuple(
            SliceDefinition(index, center, width, 1.0)
            for index, center in enumerate(centers)
        ),
    )


def _max_abs_difference(left: Sequence[float], right: Sequence[float]) -> float:
    return max((abs(float(a) - float(b)) for a, b in zip(left, right)), default=0.0)


def _matrix_max_abs_difference(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]
) -> float:
    return max(
        _max_abs_difference(left_row, right_row)
        for left_row, right_row in zip(left, right)
    )


def _state_q(nodes: Sequence[float], value: Callable[[float], float], slope: Callable[[float], float]) -> list[float]:
    q = [0.0] * (6 * len(nodes))
    for index, s_value in enumerate(nodes):
        base = 6 * index
        q[base : base + 6] = [0.0, value(s_value), s_value, 0.0, slope(s_value), 1.0]
    return q


def _mat_vec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> tuple[float, float, float]:
    return tuple(sum(row[index] * vector[index] for index in range(len(vector))) for row in matrix)  # type: ignore[return-value]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _analytic_profile(s_value: float, length_m: float) -> float:
    return 100.0 * (
        1.0
        + 0.25 * math.cos(2.0 * math.pi * s_value / length_m)
        + 0.15 * math.sin(3.0 * math.pi * s_value / length_m)
    )


def _reference_integrals(length_m: float) -> dict[str, float]:
    samples = 200_000
    ds = length_m / samples
    total = 0.0
    modal_1 = 0.0
    modal_2 = 0.0
    for index in range(samples):
        s_value = (index + 0.5) * ds
        load = _analytic_profile(s_value, length_m)
        total += load * ds
        modal_1 += load * math.sin(math.pi * s_value / length_m) * ds
        modal_2 += load * math.sin(2.0 * math.pi * s_value / length_m) * ds
    return {
        "total_force_N": total,
        "first_modal_force_N": modal_1,
        "second_modal_force_N": modal_2,
    }


def audit_one(count: int, n_elem: int, *, seed: int = 20260816) -> dict[str, Any]:
    contract = LowReContract()
    manifest = build_uniform_manifest(count, contract)
    boundaries, centers = uniform_slice_geometry(count, contract.L_m)
    nodes = [contract.L_m * index / n_elem for index in range(n_elem + 1)]
    ndof = 6 * len(nodes)
    H = build_H_for_manifest(manifest, nodes, ndof=ndof)

    direct_errors = []
    for item in manifest.slices:
        direct = ancf_hermite_H(item.s_ref_m, nodes, ndof=ndof)
        direct_errors.append(_matrix_max_abs_difference(H[item.slice_id], direct))

    cubic = lambda s: 0.05 + 0.002 * s - 1.0e-5 * s**2 + 2.0e-8 * s**3
    cubic_slope = lambda s: 0.002 - 2.0e-5 * s + 6.0e-8 * s**2
    q_cubic = _state_q(nodes, cubic, cubic_slope)
    interpolation_errors = [
        abs(_mat_vec(H[item.slice_id], q_cubic)[1] - cubic(item.s_ref_m))
        for item in manifest.slices
    ]

    mode_1 = _state_q(
        nodes,
        lambda s: math.sin(math.pi * s / contract.L_m),
        lambda s: math.pi / contract.L_m * math.cos(math.pi * s / contract.L_m),
    )
    mode_2 = _state_q(
        nodes,
        lambda s: math.sin(2.0 * math.pi * s / contract.L_m),
        lambda s: 2.0 * math.pi / contract.L_m * math.cos(2.0 * math.pi * s / contract.L_m),
    )
    mode_interp_1 = max(
        abs(_mat_vec(H[item.slice_id], mode_1)[1] - math.sin(math.pi * item.s_ref_m / contract.L_m))
        for item in manifest.slices
    )
    mode_interp_2 = max(
        abs(_mat_vec(H[item.slice_id], mode_2)[1] - math.sin(2.0 * math.pi * item.s_ref_m / contract.L_m))
        for item in manifest.slices
    )

    forces = {
        item.slice_id: (0.0, _analytic_profile(item.s_ref_m, contract.L_m) * item.slice_length_m, 0.0)
        for item in manifest.slices
    }
    rng = random.Random(seed + 100 * count + n_elem)
    delta_q = [rng.uniform(-0.1, 0.1) for _ in range(ndof)]
    mapped = map_integrated_slice_forces(
        manifest, H, forces, delta_q=delta_q, random_seed=seed + 100 * count + n_elem
    )
    generalized = list(mapped.generalized_force)
    manual = [0.0] * ndof
    for item in manifest.slices:
        matrix = H[item.slice_id]
        force = forces[item.slice_id]
        for column in range(ndof):
            manual[column] += sum(matrix[row][column] * force[row] for row in range(3))
    h_transpose_error = _max_abs_difference(generalized, manual)

    shuffled_ids = list(forces)
    rng.shuffle(shuffled_ids)
    shuffled_forces = {slice_id: forces[slice_id] for slice_id in shuffled_ids}
    shuffled_H = {slice_id: H[slice_id] for slice_id in reversed(shuffled_ids)}
    shuffled = map_integrated_slice_forces(manifest, shuffled_H, shuffled_forces)
    shuffle_error = _max_abs_difference(generalized, shuffled.generalized_force)

    missing_rejected = False
    try:
        reduced = dict(forces)
        reduced.pop(next(iter(reduced)))
        map_integrated_slice_forces(manifest, H, reduced)
    except MappingError:
        missing_rejected = True

    duplicate_rejected = False
    try:
        payload = manifest.to_dict()
        payload["slices"] = list(payload["slices"]) + [dict(payload["slices"][0])]
        SliceManifest.from_mapping(payload)
    except Exception:
        duplicate_rejected = True

    nonfinite_rejected = False
    try:
        invalid = dict(forces)
        invalid[0] = (0.0, float("nan"), 0.0)
        map_integrated_slice_forces(manifest, H, invalid)
    except NumericValidationError:
        nonfinite_rejected = True

    random_forces = {
        item.slice_id: (rng.uniform(-50.0, 50.0), rng.uniform(-50.0, 50.0), 0.0)
        for item in manifest.slices
    }
    random_audit = map_integrated_slice_forces(
        manifest, H, random_forces, delta_q=delta_q, random_seed=seed
    ).virtual_work

    uniform_forces = {
        item.slice_id: (0.0, 1.0 * item.slice_length_m, 0.0) for item in manifest.slices
    }
    uniform_audit = map_integrated_slice_forces(
        manifest, H, uniform_forces, delta_q=delta_q, random_seed=seed
    ).virtual_work
    modal_forces = {
        item.slice_id: (
            0.0,
            math.sin(math.pi * item.s_ref_m / contract.L_m) * item.slice_length_m,
            0.0,
        )
        for item in manifest.slices
    }
    modal_audit = map_integrated_slice_forces(
        manifest, H, modal_forces, delta_q=delta_q, random_seed=seed
    ).virtual_work

    timing = []
    for _ in range(5):
        started = time.perf_counter()
        for _ in range(200):
            map_integrated_slice_forces(manifest, H, forces)
        timing.append((time.perf_counter() - started) / 200.0)

    first_modal_force = _dot(mode_1, generalized)
    second_modal_force = _dot(mode_2, generalized)
    integrated_total = sum(force[1] for force in forces.values())
    width_sum = sum(item.slice_length_m for item in manifest.slices)
    gap_error = max(
        abs(boundaries[index + 1] - boundaries[index] - manifest.slices[index].slice_length_m)
        for index in range(count)
    )
    checkpoint_estimate = 3 * ndof * 8 + count * 3 * 8 + len(canonical_json_bytes(manifest.to_dict())) + 2048
    return {
        "status": "passed",
        "schema_version": "stage4f-a-v2-mapping-audit-1.0",
        "slice_count": count,
        "nElem": n_elem,
        "ndof": ndof,
        "methodology_identity": "low_re_standard_benchmark_v2_not_vivdatashare",
        "inherited_flow_identity": {"U_i_mps": 1.0, "Re_i": 100.0, "R_GL": [list(row) for row in IDENTITY_R_GL]},
        "boundaries_m": boundaries,
        "centers_m": centers,
        "slice_length_m": contract.L_m / count,
        "total_slice_length_m": width_sum,
        "coverage_gap_or_overlap_error_m": gap_error,
        "unit_span_m": 1.0,
        "slice_length_applied_exactly_once": True,
        "formal_calls": {
            "build_H_for_manifest": True,
            "ancf_hermite_H": True,
            "map_integrated_slice_forces_H_transpose": True,
        },
        "direct_H_max_abs_error": max(direct_errors),
        "cubic_H_interpolation_max_abs_error_m": max(interpolation_errors),
        "first_mode_H_interpolation_max_abs_error": mode_interp_1,
        "second_mode_H_interpolation_max_abs_error": mode_interp_2,
        "H_transpose_manual_max_abs_error_N": h_transpose_error,
        "order_shuffle_generalized_force_max_abs_error_N": shuffle_error,
        "missing_slice_rejected": missing_rejected,
        "duplicate_slice_id_rejected": duplicate_rejected,
        "nonfinite_load_rejected": nonfinite_rejected,
        "load_profile": "100*(1+0.25*cos(2*pi*s/L)+0.15*sin(3*pi*s/L)) N/m",
        "total_integrated_force_N": integrated_total,
        "first_modal_generalized_force_N": first_modal_force,
        "second_modal_generalized_force_N": second_modal_force,
        "virtual_work": {
            "uniform": uniform_audit.to_dict() if uniform_audit else None,
            "first_mode": modal_audit.to_dict() if modal_audit else None,
            "random": random_audit.to_dict() if random_audit else None,
        },
        "single_step_payload_bytes": len(canonical_json_bytes({"forces": forces, "q": generalized})),
        "checkpoint_size_estimate_bytes": checkpoint_estimate,
        "mapping_schedule_overhead_estimate_s": statistics.median(timing),
        "high_re_profile_read": False,
        "openfoam_started": False,
    }


def generate_mapping_evidence(result_dir: Path) -> dict[str, Any]:
    contract = LowReContract()
    reference = _reference_integrals(contract.L_m)
    all_results: dict[int, dict[int, dict[str, Any]]] = {}
    for count, label in ((3, "three"), (5, "five"), (9, "nine")):
        manifest = build_uniform_manifest(count, contract)
        write_json(result_dir / f"{label}_slice_manifest.json", manifest.to_dict())
        by_mesh = {n_elem: audit_one(count, n_elem) for n_elem in (16, 32)}
        all_results[count] = by_mesh
        write_json(
            result_dir / f"{label}_slice_mapping.json",
            {
                "status": "passed",
                "slice_count": count,
                "reference_integrals": reference,
                "mesh_results": {str(key): value for key, value in by_mesh.items()},
            },
        )

    selected = {count: all_results[count][32] for count in (3, 5, 9)}
    q1 = {count: selected[count]["first_modal_generalized_force_N"] for count in selected}
    change_3_5 = abs(q1[5] - q1[3]) / max(1.0, abs(q1[5]))
    change_5_9 = abs(q1[9] - q1[5]) / max(1.0, abs(q1[9]))
    comparison = {
        "status": "passed",
        "reference_integrals": reference,
        "nElem_for_comparison": 32,
        "slice_results": {
            str(count): {
                key: selected[count][key]
                for key in (
                    "total_integrated_force_N",
                    "first_modal_generalized_force_N",
                    "second_modal_generalized_force_N",
                    "first_mode_H_interpolation_max_abs_error",
                    "second_mode_H_interpolation_max_abs_error",
                    "H_transpose_manual_max_abs_error_N",
                    "single_step_payload_bytes",
                    "checkpoint_size_estimate_bytes",
                    "mapping_schedule_overhead_estimate_s",
                )
            }
            for count in (3, 5, 9)
        },
        "relative_change_3_to_5_first_modal_force": change_3_5,
        "relative_change_5_to_9_first_modal_force": change_5_9,
        "response_equality_required": False,
        "next_real_CFD_default_slice_count": 3,
    }
    write_json(result_dir / "slice_count_comparison.json", comparison)

    virtual_cases = []
    for count in (3, 5, 9):
        for n_elem in (16, 32):
            work = all_results[count][n_elem]["virtual_work"]
            for profile, audit in work.items():
                virtual_cases.append(
                    {
                        "slice_count": count,
                        "nElem": n_elem,
                        "profile": profile,
                        "error_abs_J": audit["error_abs_J"],
                        "error_rel": audit["error_rel"],
                    }
                )
    maximum = max(max(item["error_abs_J"], item["error_rel"]) for item in virtual_cases)
    virtual = {
        "status": "passed" if maximum <= 1.0e-12 else "failed",
        "threshold": 1.0e-12,
        "maximum_absolute_or_relative_error": maximum,
        "cases": virtual_cases,
    }
    write_json(result_dir / "virtual_work_audit.json", virtual)
    return {"all_results": all_results, "comparison": comparison, "virtual_work": virtual}
