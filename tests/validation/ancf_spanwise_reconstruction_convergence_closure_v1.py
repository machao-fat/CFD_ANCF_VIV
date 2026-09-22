"""Measure finite-slice reconstruction error against continuous exact loads."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import pathlib
import subprocess
import sys
from collections import defaultdict
from typing import Callable

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
PREFIX = "ANCF_SPANWISE_RECONSTRUCTION_CONVERGENCE_CLOSURE_V1"
EXPECTED_HEAD = "29b364cdb87e0829c0c2b49ed727957240b40c1e"
EXPECTED_TAG_TARGET = "dfb1a3e7e92220a2e4c9400317de372e637095eb"
LENGTH = 10.0
ELEMENTS = 11
S_REF = 5.0
SAMPLE_COUNTS = (5, 9, 17, 33, 65)
SCALE_FLOOR = 1.0
FORMAL_TOLERANCE = 2.0e-12


def exact_load(case_id: str, s: float) -> np.ndarray:
    if case_id == "case_a_sinusoidal":
        return np.array([
            1.25 + 0.37 * math.sin(0.43 * s) + 0.23 * math.cos(0.71 * s),
            -0.42 + 0.29 * math.sin(0.37 * s + 0.23),
            0.31 + 0.11 * math.cos(0.29 * s + 0.17),
        ], dtype=np.float64)
    if case_id == "case_b_mixed_smooth":
        return np.array([
            0.80 + 0.45 * math.exp(0.12 * s / LENGTH) +
            0.18 * math.sin(0.63 * s + 0.11),
            -0.35 + 0.22 * math.cos(0.51 * s + 0.37),
            0.25 + 0.14 * math.exp(-0.08 * s / LENGTH) +
            0.09 * math.sin(0.27 * s + 0.19),
        ], dtype=np.float64)
    if case_id == "exact_linear_sanity":
        return np.array([0.80 + 0.13 * s, -0.40 + 0.07 * s, 0.20 - 0.05 * s],
                        dtype=np.float64)
    raise ValueError(f"unknown case {case_id}")


def sample_positions(count: int, nonuniform: bool) -> np.ndarray:
    xi = np.linspace(0.0, 1.0, count, dtype=np.float64)
    if nonuniform:
        xi = xi + 0.20 * np.sin(2.0 * np.pi * xi) / (2.0 * np.pi)
    return LENGTH * xi


def hermite_matrix(s: float) -> np.ndarray:
    element_length = LENGTH / ELEMENTS
    element = min(int(math.floor(s / element_length)), ELEMENTS - 1)
    x = s - element * element_length
    xi = x / element_length
    xi2 = xi * xi
    xi3 = xi2 * xi
    h = (
        1.0 - 3.0 * xi2 + 2.0 * xi3,
        element_length * (xi - 2.0 * xi2 + xi3),
        3.0 * xi2 - 2.0 * xi3,
        element_length * (-xi2 + xi3),
    )
    result = np.zeros((3, 6 * (ELEMENTS + 1)), dtype=np.float64)
    for block, value in enumerate(h):
        base = 6 * element + 3 * block
        for component in range(3):
            result[component, base + component] = value
    return result


def linear_reconstruction(s: float, positions: np.ndarray, values: np.ndarray) -> np.ndarray:
    if s <= positions[0]:
        return values[0]
    if s >= positions[-1]:
        return values[-1]
    upper = int(np.searchsorted(positions, s, side="right"))
    left = upper - 1
    fraction = (s - positions[left]) / (positions[upper] - positions[left])
    return values[left] + fraction * (values[upper] - values[left])


def constant_reconstruction(s: float, positions: np.ndarray, values: np.ndarray) -> np.ndarray:
    # Validation-only PiecewiseConstant comparator: nearest-sample Voronoi cells.
    boundaries = np.concatenate((
        np.array([0.0]),
        0.5 * (positions[:-1] + positions[1:]),
        np.array([LENGTH]),
    ))
    index = min(max(int(np.searchsorted(boundaries, s, side="right") - 1), 0),
                values.shape[0] - 1)
    return values[index]


def integrate_field(field: Callable[[float], np.ndarray], order: int,
                    extra_breaks: tuple[float, ...] = ()) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nodes, weights = np.polynomial.legendre.leggauss(order)
    q = np.zeros(6 * (ELEMENTS + 1), dtype=np.float64)
    resultant = np.zeros(3, dtype=np.float64)
    moment = np.zeros(3, dtype=np.float64)
    element_length = LENGTH / ELEMENTS
    for element in range(ELEMENTS):
        left = element * element_length
        right = (element + 1) * element_length
        breaks = [left, right]
        breaks.extend(value for value in extra_breaks if left < value < right)
        breaks = sorted(set(breaks))
        for sub_left, sub_right in zip(breaks[:-1], breaks[1:]):
            midpoint = 0.5 * (sub_left + sub_right)
            half_width = 0.5 * (sub_right - sub_left)
            for node, weight in zip(nodes, weights):
                s = midpoint + half_width * node
                value = field(s)
                factor = half_width * weight
                q += factor * hermite_matrix(s).T @ value
                resultant += factor * value
                moment += factor * (s - S_REF) * value
    return q, resultant, moment


def integrate_squared_difference(left: Callable[[float], np.ndarray],
                                 right: Callable[[float], np.ndarray],
                                 order: int, extra_breaks: tuple[float, ...]) -> float:
    nodes, weights = np.polynomial.legendre.leggauss(order)
    total = 0.0
    element_length = LENGTH / ELEMENTS
    for element in range(ELEMENTS):
        element_left = element * element_length
        element_right = (element + 1) * element_length
        breaks = [element_left, element_right]
        breaks.extend(value for value in extra_breaks
                      if element_left < value < element_right)
        breaks = sorted(set(breaks))
        for sub_left, sub_right in zip(breaks[:-1], breaks[1:]):
            midpoint = 0.5 * (sub_left + sub_right)
            half_width = 0.5 * (sub_right - sub_left)
            for node, weight in zip(nodes, weights):
                s = midpoint + half_width * node
                difference = left(s) - right(s)
                total += half_width * weight * float(difference @ difference)
    return math.sqrt(total)


def relative(error: float, reference: np.ndarray) -> float:
    return float(error / max(float(np.linalg.norm(reference)), SCALE_FLOOR))


def q_relative(lhs: np.ndarray, rhs: np.ndarray) -> float:
    return relative(float(np.linalg.norm(lhs - rhs)), rhs)


def parse_production(executable: pathlib.Path) -> tuple[list[dict], pathlib.Path]:
    process = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, check=False)
    raw = process.stdout + process.stderr
    raw_path = OUT / f"{PREFIX}_RAW.txt"
    raw_path.write_bytes(raw)
    if process.returncode != 0:
        raise RuntimeError(f"closure production verifier failed: rc={process.returncode}")
    records = [json.loads(line) for line in process.stdout.decode("utf-8").splitlines() if line.strip()]
    if len(records) != 21:
        raise RuntimeError(f"unexpected production record count: {len(records)}")
    return records, raw_path


def compute_record(production_q: np.ndarray, case_id: str, family: str,
                   mode: str, positions: np.ndarray, sample_values: np.ndarray,
                   exact_q: np.ndarray, exact_f: np.ndarray, exact_m: np.ndarray,
                   reference_uncertainty: float) -> dict:
    if mode == "PiecewiseLinearDistributed":
        field = lambda s: linear_reconstruction(s, positions, sample_values)
    elif mode == "PiecewiseConstantDistributed":
        field = lambda s: constant_reconstruction(s, positions, sample_values)
    else:
        raise ValueError(mode)
    q_h, f_h, m_h = integrate_field(field, 64, tuple(positions))
    q_abs = float(np.linalg.norm(production_q - exact_q))
    result = {
        "case_id": case_id,
        "family": family,
        "mode": mode,
        "Ns": int(len(positions)),
        "h_max": float(np.max(np.diff(positions))),
        "E_Q_abs": q_abs,
        "E_Q_rel": q_relative(production_q, exact_q),
        "E_total_force": relative(float(np.linalg.norm(f_h - exact_f)), exact_f),
        "E_first_moment": relative(float(np.linalg.norm(m_h - exact_m)), exact_m),
        "E_Q_comparator_reference": q_relative(q_h, exact_q),
        "E_total_force_abs": float(np.linalg.norm(f_h - exact_f)),
        "E_first_moment_abs": float(np.linalg.norm(m_h - exact_m)),
        "reference_uncertainty": float(reference_uncertainty),
        "L2_reconstruction_error": integrate_squared_difference(
            field, lambda s: exact_load(case_id, s), 128, tuple(positions)),
        "observed_order_if_defined": None,
        "production_q_recomputed_vs_reported_rel": q_relative(q_h, production_q),
    }
    return result


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    fields = [
        "case_id", "family", "mode", "Ns", "h_max", "E_Q_abs", "E_Q_rel",
        "E_total_force", "E_first_moment", "reference_uncertainty",
        "observed_order_if_defined", "E_Q_comparator_reference",
        "E_total_force_abs", "E_first_moment_abs", "L2_reconstruction_error",
        "production_q_recomputed_vs_reported_rel",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: closure.py <production-verifier.exe>")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != EXPECTED_HEAD:
        raise RuntimeError("production HEAD changed")
    if subprocess.check_output(["git", "rev-list", "-n", "1", "ancf-coupling-baseline-v1"],
                               cwd=ROOT, text=True).strip() != EXPECTED_TAG_TARGET:
        raise RuntimeError("baseline tag target changed")
    if subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode != 0 or \
            subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
        raise RuntimeError("tracked/index state is dirty")

    OUT.mkdir(parents=True, exist_ok=True)
    records, raw_path = parse_production(pathlib.Path(sys.argv[1]).resolve())
    by_key = {(r["case_id"], r["family"], int(r["Ns"])): np.asarray(r["q"], dtype=np.float64)
              for r in records}
    rows: list[dict] = []
    reference_audit: dict = {"quadrature_orders": [32, 64, 128], "cases": {}}
    for case_id in ("case_a_sinusoidal", "case_b_mixed_smooth"):
        q32, f32, m32 = integrate_field(lambda s, c=case_id: exact_load(c, s), 32)
        q64, f64, m64 = integrate_field(lambda s, c=case_id: exact_load(c, s), 64)
        q128, f128, m128 = integrate_field(lambda s, c=case_id: exact_load(c, s), 128)
        uncertainty = max(
            q_relative(q32, q64), q_relative(q64, q128),
            relative(float(np.linalg.norm(f32 - f64)), f64),
            relative(float(np.linalg.norm(f64 - f128)), f128),
            relative(float(np.linalg.norm(m32 - m64)), m64),
            relative(float(np.linalg.norm(m64 - m128)), m128),
        )
        reference_audit["cases"][case_id] = {
            "q32_vs_q64_relative": q_relative(q32, q64),
            "q64_vs_q128_relative": q_relative(q64, q128),
            "reference_uncertainty_max": uncertainty,
            "resultant_32_vs_64_relative": relative(float(np.linalg.norm(f32 - f64)), f64),
            "resultant_64_vs_128_relative": relative(float(np.linalg.norm(f64 - f128)), f128),
            "moment_32_vs_64_relative": relative(float(np.linalg.norm(m32 - m64)), m64),
            "moment_64_vs_128_relative": relative(float(np.linalg.norm(m64 - m128)), m128),
            "q128_norm": float(np.linalg.norm(q128)),
            "resultant_128": f128.tolist(),
            "moment_128": m128.tolist(),
        }
        positions_by_family = {family: sample_positions(5, family == "nonuniform")
                               for family in ("uniform", "nonuniform")}
        for family, first_positions in positions_by_family.items():
            for count in SAMPLE_COUNTS:
                positions = sample_positions(count, family == "nonuniform")
                values = np.asarray([exact_load(case_id, float(s)) for s in positions])
                row = compute_record(
                    by_key[(case_id, family, count)], case_id, family,
                    "PiecewiseLinearDistributed", positions, values,
                    q128, f128, m128, uncertainty)
                row["E_Q_constant"] = compute_record(
                    np.zeros_like(q128), case_id, family,
                    "PiecewiseConstantDistributed", positions, values,
                    q128, f128, m128, uncertainty)["E_Q_comparator_reference"]
                row["E_total_force_constant"] = compute_record(
                    np.zeros_like(q128), case_id, family,
                    "PiecewiseConstantDistributed", positions, values,
                    q128, f128, m128, uncertainty)["E_total_force"]
                row["E_first_moment_constant"] = compute_record(
                    np.zeros_like(q128), case_id, family,
                    "PiecewiseConstantDistributed", positions, values,
                    q128, f128, m128, uncertainty)["E_first_moment"]
                rows.append(row)

    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["case_id"], row["family"], row["mode"])].append(row)
    for group_rows in grouped.values():
        group_rows.sort(key=lambda item: item["Ns"])
        for left, right in zip(group_rows[:-1], group_rows[1:]):
            if left["E_Q_rel"] > 0.0 and right["E_Q_rel"] > 0.0:
                left["observed_order_if_defined"] = math.log(
                    left["E_Q_rel"] / right["E_Q_rel"]) / math.log(
                        left["h_max"] / right["h_max"])

    uniform_rows = [row for row in rows if row["family"] == "uniform"]
    nonuniform_rows = [row for row in rows if row["family"] == "nonuniform"]
    write_csv(OUT / f"{PREFIX}_UNIFORM.csv", uniform_rows)
    write_csv(OUT / f"{PREFIX}_NONUNIFORM.csv", nonuniform_rows)

    exact_q128, _, _ = integrate_field(lambda s: exact_load("exact_linear_sanity", s), 128)
    exact_q32, _, _ = integrate_field(lambda s: exact_load("exact_linear_sanity", s), 32)
    exact_positions = sample_positions(5, False)
    exact_sanity_q = by_key[("exact_linear_sanity", "uniform", 5)]
    exact_sanity = {
        "E_Q_abs": float(np.linalg.norm(exact_sanity_q - exact_q128)),
        "E_Q_rel": q_relative(exact_sanity_q, exact_q128),
        "reference_32_vs_128_relative": q_relative(exact_q32, exact_q128),
        "Ns": 5,
        "endpoints": [float(exact_positions[0]), float(exact_positions[-1])],
        "pass": q_relative(exact_sanity_q, exact_q128) <= FORMAL_TOLERANCE,
    }

    smooth_gate = {}
    for case_id in ("case_a_sinusoidal", "case_b_mixed_smooth"):
        case_rows = sorted([row for row in uniform_rows if row["case_id"] == case_id],
                           key=lambda item: item["Ns"])
        errors = [row["E_Q_rel"] for row in case_rows]
        positive_steps = sum(right < left for left, right in zip(errors[:-1], errors[1:]))
        finest = case_rows[-1]
        smooth_gate[case_id] = {
            "coarse_error": errors[0],
            "finest_error": errors[-1],
            "overall_decrease": errors[-1] < errors[0],
            "positive_adjacent_steps": positive_steps,
            "not_roundoff_floor": errors[0] > 1.0e-12,
            "reference_uncertainty_below_finest_by_3_orders":
                finest["reference_uncertainty"] < finest["E_Q_rel"] / 1000.0,
            "pass": errors[-1] < errors[0] and positive_steps >= 3 and
                    errors[0] > 1.0e-12 and
                    finest["reference_uncertainty"] < finest["E_Q_rel"] / 1000.0,
        }
    nonuniform_finite = all(math.isfinite(row["E_Q_rel"]) for row in nonuniform_rows)
    nonuniform_trend = {}
    for case_id in ("case_a_sinusoidal", "case_b_mixed_smooth"):
        case_rows = sorted([row for row in nonuniform_rows if row["case_id"] == case_id],
                           key=lambda item: item["Ns"])
        errors = [row["E_Q_rel"] for row in case_rows]
        nonuniform_trend[case_id] = {
            "coarse_error": errors[0], "finest_error": errors[-1],
            "positive_adjacent_steps": sum(right < left for left, right in zip(errors[:-1], errors[1:])),
            "pass": errors[-1] < errors[0] and
                    sum(right < left for left, right in zip(errors[:-1], errors[1:])) >= 3,
        }

    result = {
        "schema_version": "ANCF_SPANWISE_RECONSTRUCTION_CONVERGENCE_CLOSURE_V1",
        "status": "PASS" if exact_sanity["pass"] and all(item["pass"] for item in smooth_gate.values())
                  and nonuniform_finite and all(item["pass"] for item in nonuniform_trend.values()) else "FAIL",
        "classification": "ANCF_SPANWISE_RECONSTRUCTION_CONVERGENCE_CLOSURE_V1",
        "production_commit": EXPECTED_HEAD,
        "baseline_tag": "ancf-coupling-baseline-v1",
        "baseline_tag_target": EXPECTED_TAG_TARGET,
        "fixed_structural_model": {"length_m": LENGTH, "elements": ELEMENTS,
                                    "active_interval_m": [0.0, LENGTH],
                                    "quadrature": "production Gauss-3"},
        "exact_reference": reference_audit,
        "exact_linear_sanity": exact_sanity,
        "uniform_gate": smooth_gate,
        "nonuniform_gate": {"finite": nonuniform_finite, "trend": nonuniform_trend,
                             "pass": nonuniform_finite and all(item["pass"]
                                                               for item in nonuniform_trend.values())},
        "rows": rows,
        "piecewise_constant_comparator":
            "validation-only nearest-sample Voronoi comparator; no production constant mode added",
        "prior_v1_machine_precision_evidence":
            "same-f_h production-vs-independent-reference integration evidence, not continuous-load reconstruction convergence",
        "production_modifications": 0,
        "execution_counts": {"G1": 0, "CFD": 0, "preCICE": 0, "OpenFOAM": 0,
                              "FSI": 0, "VIV": 0, "arbitrary_N_coupling": 0},
        "raw_sha256": sha(raw_path),
    }
    result_path = OUT / f"{PREFIX}_RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    reference_md = OUT / f"{PREFIX}_EXACT_REFERENCE_AUDIT.md"
    reference_md.write_text(
        "# Exact-reference audit\n\n"
        "The reference evaluates the exact functions in the frozen protocol directly, "
        "using an independent Python Hermite matrix and 32-, 64-, and 128-point "
        "Gauss--Legendre quadrature on each fixed element. The 128-point result is "
        "used as Q_exact. The maximum 32/64 and 64/128 discrepancies are persisted "
        "per case in the result JSON; they are compared with the finest measured "
        "slice reconstruction error. No production reconstruction function or "
        "production Gauss-3 result is used to form Q_exact.\n\n"
        + json.dumps(reference_audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report_lines = [
        f"# {PREFIX} — report", "", "## Final classification", "",
        f"`{result['status']}` — `ANCF_SPANWISE_RECONSTRUCTION_CONVERGENCE_CLOSURE_V1`.",
        "", f"Production commit: `{EXPECTED_HEAD}`.",
        "", "## Scientific distinction", "",
        "V1's approximately 1e-15 values were confirmed to compare production "
        "integration of the same reconstructed f_h with an independent reference. "
        "This closure instead compares finite-slice f_h^(Ns) against f_exact.",
        "", "## Exact functions and fixed model", "",
        "Case A and Case B are frozen in the protocol. The structural model is "
        f"fixed at L={LENGTH} m and Ne={ELEMENTS}; only Ns and sample positions vary.",
        "", "## Exact-linear sanity", "",
        json.dumps(exact_sanity, indent=2), "",
        "## Uniform PiecewiseLinear convergence", "",
        "| case | Ns | h_max | E_Q_rel | E_total_force | E_first_moment | reference uncertainty | order |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(uniform_rows, key=lambda item: (item["case_id"], item["Ns"])):
        order = "" if row["observed_order_if_defined"] is None else f"{row['observed_order_if_defined']:.6g}"
        report_lines.append(
            f"| {row['case_id']} | {row['Ns']} | {row['h_max']:.8g} | {row['E_Q_rel']:.8e} | "
            f"{row['E_total_force']:.8e} | {row['E_first_moment']:.8e} | "
            f"{row['reference_uncertainty']:.8e} | {order} |")
    report_lines.extend(["", "## PiecewiseConstant comparator", "",
                         "The constant comparator is validation-only nearest-sample "
                         "Voronoi reconstruction because production V1 did not add a "
                         "constant mode. Its metrics are in the uniform CSV; the "
                         "linear-vs-constant comparison is not used as an individual "
                         "scalar gate.", "",
                         "| case | Ns | E_Q_linear | E_Q_constant | E_total_force_linear | E_total_force_constant |",
                         "|---|---:|---:|---:|---:|---:|"])
    for row in sorted(uniform_rows, key=lambda item: (item["case_id"], item["Ns"])):
        report_lines.append(
            f"| {row['case_id']} | {row['Ns']} | {row['E_Q_rel']:.8e} | "
            f"{row['E_Q_constant']:.8e} | {row['E_total_force']:.8e} | "
            f"{row['E_total_force_constant']:.8e} |")
    report_lines.extend(["", "## Nonuniform bounded family", "",
                         json.dumps(nonuniform_trend, indent=2), "",
                         "## Scope and non-claims", "",
                         "Production source modifications: 0. G1, CFD, OpenFOAM, "
                         "preCICE, FSI, VIV, arbitrary-N coupling, and production "
                         "single-/three-slice cases executed: 0. This evidence does "
                         "not establish slice-number independence for VIV."])
    report_path = OUT / f"{PREFIX}_REPORT.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    manifest_paths = [
        OUT / f"{PREFIX}_PROTOCOL.md", reference_md,
        OUT / f"{PREFIX}_UNIFORM.csv", OUT / f"{PREFIX}_NONUNIFORM.csv",
        result_path, report_path, raw_path,
        ROOT / "tests/validation/ancf_spanwise_reconstruction_convergence_closure_v1.cpp",
        ROOT / "tests/validation/ancf_spanwise_reconstruction_convergence_closure_v1.py",
    ]
    manifest = OUT / f"{PREFIX}_SHA256_MANIFEST.txt"
    manifest_lines = [
        "schema_version=1",
        f"production_commit={EXPECTED_HEAD}",
        f"baseline_tag_target={EXPECTED_TAG_TARGET}",
        "NOTE=manifest hash omitted to avoid self-reference",
    ]
    for path in manifest_paths:
        manifest_lines.append(f"{path.relative_to(ROOT).as_posix()} {sha(path)}")
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "result": str(result_path),
                      "report": str(report_path), "manifest": str(manifest)}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
