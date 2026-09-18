"""Offline, independent verification for the spanwise distributed-load API.

The C++ companion emits production generalized loads for fixed deterministic
cases.  This script reconstructs the cubic Hermite interpolation and performs
an independent high-order Gauss integration, so the expected loads are not
obtained from the production implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
import subprocess
import sys
from typing import Iterable

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "runtime" / "ANCF_validation"
PREFIX = "ANCF_SPANWISE_DISTRIBUTED_LOAD_RECONSTRUCTION_V1"


def hermite_matrix(s: float, length: float, elements: int) -> np.ndarray:
    le = length / elements
    element = min(int(math.floor(s / le)), elements - 1)
    x = s - element * le
    xi = x / le
    xi2 = xi * xi
    xi3 = xi2 * xi
    h = (
        1.0 - 3.0 * xi2 + 2.0 * xi3,
        le * (xi - 2.0 * xi2 + xi3),
        3.0 * xi2 - 2.0 * xi3,
        le * (-xi2 + xi3),
    )
    result = np.zeros((3, 6 * (elements + 1)), dtype=np.float64)
    for local_block, value in enumerate(h):
        node_component = 6 * element + 3 * local_block
        for component in range(3):
            result[component, node_component + component] = value
    return result


def reconstructed_force(
    s: float,
    active_min: float,
    active_max: float,
    positions: np.ndarray,
    values: np.ndarray,
) -> np.ndarray:
    if s < active_min or s > active_max:
        return np.zeros(3, dtype=np.float64)
    if s <= positions[0]:
        return values[0].copy()
    if s >= positions[-1]:
        return values[-1].copy()
    upper = int(np.searchsorted(positions, s, side="right"))
    left = upper - 1
    fraction = (s - positions[left]) / (positions[upper] - positions[left])
    return values[left] + fraction * (values[upper] - values[left])


def reference_load(
    length: float,
    elements: int,
    active_min: float,
    active_max: float,
    positions: Iterable[float],
    values: Iterable[Iterable[float]],
) -> tuple[np.ndarray, np.ndarray]:
    positions_array = np.asarray(tuple(positions), dtype=np.float64)
    values_array = np.asarray(tuple(values), dtype=np.float64)
    result = np.zeros(6 * (elements + 1), dtype=np.float64)
    nodes, weights = np.polynomial.legendre.leggauss(32)
    breaks = [active_min, active_max]
    breaks.extend(float(value) for value in positions_array
                  if active_min < value < active_max)
    breaks = sorted(set(breaks))
    le = length / elements
    for element in range(elements):
        element_min = element * le
        element_max = (element + 1) * le
        left = max(element_min, active_min)
        right = min(element_max, active_max)
        if right <= left:
            continue
        local_breaks = [left, right]
        local_breaks.extend(value for value in breaks if left < value < right)
        local_breaks = sorted(set(local_breaks))
        for sub_left, sub_right in zip(local_breaks[:-1], local_breaks[1:]):
            midpoint = 0.5 * (sub_left + sub_right)
            half_width = 0.5 * (sub_right - sub_left)
            for node, weight in zip(nodes, weights):
                s = midpoint + half_width * node
                result += (half_width * weight *
                           hermite_matrix(s, length, elements).T @
                           reconstructed_force(s, active_min, active_max,
                                               positions_array, values_array))
    return result, np.asarray([0.0, 0.0, 0.0])


def exact_total_force(
    active_min: float,
    active_max: float,
    positions: np.ndarray,
    values: np.ndarray,
) -> np.ndarray:
    total = np.zeros(3, dtype=np.float64)
    if active_min < positions[0]:
        total += (positions[0] - active_min) * values[0]
    for left, right, force_left, force_right in zip(
            positions[:-1], positions[1:], values[:-1], values[1:]):
        width = right - left
        total += 0.5 * width * (force_left + force_right)
    if active_max > positions[-1]:
        total += (active_max - positions[-1]) * values[-1]
    return total


def legacy_reference(length: float, elements: int, positions: np.ndarray,
                     values: np.ndarray) -> np.ndarray:
    result = np.zeros(6 * (elements + 1), dtype=np.float64)
    for position, force in zip(positions, values):
        result += hermite_matrix(float(position), length, elements).T @ force
    return result


def sine_case(sample_count: int) -> tuple[float, int, float, float, np.ndarray, np.ndarray]:
    length = 10.0
    elements = 11
    positions = np.linspace(0.0, length, sample_count)
    values = np.column_stack((np.sin(0.7 * positions),
                              0.5 * np.cos(0.7 * positions),
                              0.2 * np.sin(0.3 * positions)))
    return length, elements, 0.0, length, positions, values


def norm(value: np.ndarray) -> float:
    return float(np.linalg.norm(value))


def run(executable: pathlib.Path) -> dict:
    process = subprocess.run([str(executable)], cwd=ROOT, text=True,
                             capture_output=True, check=False)
    raw_path = OUT_DIR / f"{PREFIX}_RAW.txt"
    raw_path.write_text(process.stdout + process.stderr, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"offline C++ verifier failed: rc={process.returncode}\n{process.stderr}")
    records = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    by_name = {record["name"]: record for record in records}
    tests: list[dict] = []

    specs = {
        "constant": (10.0, 4, 1.0, 9.0, [1.7, 4.9, 8.2],
                     [[2.0, -1.0, 0.5]] * 3),
        "linear": (10.0, 7, 0.5, 9.5, [0.5, 4.0, 9.5],
                   [[1.0 + 0.2 * s, -2.0 + 0.3 * s, 0.5 - 0.1 * s]
                    for s in [0.5, 4.0, 9.5]]),
        "nonuniform_samples": (10.0, 11, 0.0, 10.0, [0.4, 1.7, 6.2, 9.6],
                                [[0.2, 1.0, -0.5], [1.1, -0.4, 0.3],
                                 [-0.7, 0.8, 1.2], [0.4, 0.2, -0.1]]),
        "endpoint_extension": (10.0, 4, 0.3, 9.7, [1.2, 4.6, 8.4],
                                [[1.5, -0.2, 0.4], [-0.5, 0.8, 0.1],
                                 [0.9, 0.3, -0.6]]),
        "zero_outside": (10.0, 7, 2.0, 8.0, [3.0, 5.0, 7.0],
                          [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0],
                           [-1.0, 0.0, 0.5]]),
        "ne_4_ns_3": (10.0, 4, 0.5, 9.5, [1.1, 4.4, 8.8],
                       [[0.2, 1.0, 0.0], [1.2, -0.5, 0.4], [-0.3, 0.8, 1.1]]),
        "ne_7_ns_5": (10.0, 7, 0.5, 9.5, [0.7, 2.3, 4.1, 7.6, 9.2],
                       [[0.2, 1.0, 0.0], [0.8, -0.2, 0.4], [1.1, 0.5, 0.2],
                        [-0.4, 0.7, 0.9], [0.3, 0.1, -0.6]]),
        "ne_11_ns_4": (10.0, 11, 0.5, 9.5, [1.1, 3.9, 6.4, 8.8],
                        [[0.2, 1.0, 0.0], [1.2, -0.5, 0.4], [-0.3, 0.8, 1.1],
                         [0.5, -0.1, 0.2]]),
    }
    for name, (length, elements, active_min, active_max, positions, values) in specs.items():
        production = np.asarray(by_name[name]["q"], dtype=np.float64)
        reference, _ = reference_load(length, elements, active_min, active_max,
                                      positions, values)
        positions_array = np.asarray(positions, dtype=np.float64)
        values_array = np.asarray(values, dtype=np.float64)
        error = norm(production - reference)
        relative = error / max(norm(reference), 1.0)
        rigid_force = np.array([sum(production[6 * node + component]
                                     for node in range(elements + 1))
                                for component in range(3)])
        force_error = norm(rigid_force - exact_total_force(
            active_min, active_max, positions_array, values_array))
        delta_q = np.array([math.sin(0.13 * (index + 1)) +
                            0.2 * math.cos(0.37 * (index + 1))
                            for index in range(production.size)])
        virtual_work_error = abs(float(delta_q @ (production - reference)))
        node_positions = np.linspace(0.0, length, elements + 1)
        slices_inside = bool(np.all(np.min(np.abs(positions_array[:, None] -
                                                 node_positions[None, :]), axis=1) > 1e-12))
        passed = (relative <= 2e-12 and force_error <= 2e-12 and
                  virtual_work_error <= 2e-12 and slices_inside)
        tests.append({"name": name, "load_error_inf": float(np.max(np.abs(production - reference))),
                      "load_error_l2": error, "relative_error": relative,
                      "total_force_error_l2": force_error,
                      "virtual_work_error": virtual_work_error,
                      "slice_not_at_node": slices_inside, "pass": passed})

    legacy = np.asarray(by_name["legacy_point_lumped"]["q"], dtype=np.float64)
    legacy_expected = legacy_reference(10.0, 4, np.asarray([1.0, 4.0, 9.0]),
                                       np.asarray([[2.0, 3.0, 0.0], [1.0, 0.0, 4.0],
                                                   [-1.0, 2.0, 0.5]]))
    legacy_error = norm(legacy - legacy_expected)
    tests.append({"name": "legacy_point_lumped_compatibility",
                  "load_error_l2": legacy_error, "pass": legacy_error <= 2e-14})

    convergence = []
    for sample_count in (5, 10, 20, 40):
        length, elements, active_min, active_max, positions, values = sine_case(sample_count)
        production = np.asarray(by_name[f"sine_ns_{sample_count}"]["q"], dtype=np.float64)
        reference, _ = reference_load(length, elements, active_min, active_max, positions, values)
        convergence.append({"mode": "PiecewiseLinearDistributed", "samples": sample_count,
                            "generalized_force_l2_error": norm(production - reference),
                            "generalized_force_relative_error":
                            norm(production - reference) / max(norm(reference), 1.0),
                            "total_force_error_l2": norm(
                                np.array([sum(production[6 * node + c] for node in range(elements + 1))
                                          for c in range(3)]) -
                                exact_total_force(active_min, active_max, positions, values))})

    primary_pass = all(item["pass"] for item in tests)
    result = {
        "schema_version": "ancf_spanwise_distributed_load_reconstruction_v1.1",
        "production_executable_return_code": process.returncode,
        "production_mode": "PiecewiseLinearDistributed",
        "endpoint_policy": "NearestConstant",
        "active_region_outside_load": "exact_zero",
        "quadrature": "production Gauss-3 split at element/sample/active boundaries",
        "independent_reference": "Python NumPy 32-point Gauss-Legendre with independent Hermite evaluator",
        "tests": tests,
        "smooth_load_convergence": convergence,
        "piecewise_constant_distributed": "OPTIONAL_NOT_IMPLEMENTED_IN_V1",
        "primary_required_tests_pass": primary_pass,
        "legacy_mapping_preserved": bool(legacy_error <= 2e-14),
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest().upper(),
    }
    result_path = OUT_DIR / f"{PREFIX}_OFFLINE_VERIFICATION.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    convergence_path = OUT_DIR / f"{PREFIX}_CONVERGENCE.csv"
    convergence_lines = [
        "mode,samples,generalized_force_l2_error,generalized_force_relative_error,total_force_error_l2"
    ]
    convergence_lines.extend(
        f"{row['mode']},{row['samples']},{row['generalized_force_l2_error']:.17g},"
        f"{row['generalized_force_relative_error']:.17g},{row['total_force_error_l2']:.17g}"
        for row in convergence
    )
    convergence_path.write_text("\n".join(convergence_lines) + "\n", encoding="utf-8")
    legacy_path = OUT_DIR / f"{PREFIX}_LEGACY_REGRESSION.json"
    legacy_path.write_text(json.dumps({
        "status": "PASS" if legacy_error <= 2e-14 else "FAIL",
        "mode": "LegacyPointLumped",
        "legacy_generalized_load_l2_error": float(legacy_error),
        "tolerance": 2e-14,
        "legacy_wire_semantics": "integrated_slice_force_N",
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: ancf_spanwise_distributed_load_reconstruction_v1.py <verifier.exe>")
    report = run(pathlib.Path(sys.argv[1]).resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["primary_required_tests_pass"] else 1)
