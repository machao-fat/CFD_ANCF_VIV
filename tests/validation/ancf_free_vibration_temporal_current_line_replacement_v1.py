from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy
from scipy.linalg import eigh


HEAD = "36927c01208339f179670322799eb84d86dd2992"
PARENT = "b5e22a2fdba5961dabc2ed62a9d833f6bf649c5a"
Q_SHA = "0DCFA5E840B9C79D39091C99EB0C399DFABD4507811F2A63E77C196A6095E385"
MFF_SHA = "7A6C2133F4814411D9B39900017A068D066A0AD9679DBAA2CFDBF7EC38C3CEA1"
KFF_SHA = "7759CAB46444A7100CF6B915BA091D4C9B98F3FA8C5136E514FCD626C41E997E"
FREE_SHA = "522727C180A9ACDAB071B06819FC476EA790603931B99F5FF6F432E404C60D71"
REFERENCE_SHA = "5B25F095B2FDC066CF8D334B12A993F1D62DB1BCCD95317F8074E7EA3E3D8CEE"
F_REF = 0.19876102675389518
OMEGA_REF = 1.2488523629400028
T_REF = 5.03116740908264
DT = {
    "T80": 0.062889592613533,
    "T160": 0.0314447963067665,
    "T320": 0.01572239815338325,
    "T640": 0.007861199076691625,
}
STEPS = {"T80": 960, "T160": 1920, "T320": 3840, "T640": 7680}
REFERENCE_FREQUENCIES = np.array(
    [
        0.19876102675389518,
        0.476181930710043,
        0.8702401692325742,
        1.3985123281821055,
        2.068594917195311,
        2.8842837351244612,
    ],
    dtype=np.float64,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def sha256_array(values: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(values, dtype="<f8").tobytes(order="C")).hexdigest().upper()


def load_vector(path: Path) -> np.ndarray:
    return np.atleast_1d(np.loadtxt(path, dtype=np.float64))


def load_matrix(path: Path) -> np.ndarray:
    return np.loadtxt(path, dtype=np.float64)


def write_vector(path: Path, values: np.ndarray) -> None:
    path.write_text("".join(f"{float(v):.17g}\n" for v in values), encoding="utf-8")


def write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if path.exists():
        path.unlink()
    temporary.replace(path)


def read_history(path: Path) -> np.ndarray:
    return np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8")


def prepare(setup_dir: Path, output_dir: Path, protocol_sha: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    q = load_vector(setup_dir / "q_static.txt")
    mff = load_matrix(setup_dir / "M_ff.txt")
    kff = load_matrix(setup_dir / "K_ff.txt")
    free = [int(x) for x in (setup_dir / "free_dof.txt").read_text(encoding="utf-8").split()]
    identities = {
        "q_static": sha256_file(setup_dir / "q_static.txt"),
        "M_ff": sha256_file(setup_dir / "M_ff.txt"),
        "K_ff": sha256_file(setup_dir / "K_ff.txt"),
        "free_dof": sha256_file(setup_dir / "free_dof.txt"),
    }
    expected = {"q_static": Q_SHA, "M_ff": MFF_SHA, "K_ff": KFF_SHA, "free_dof": FREE_SHA}
    regressions = {name: identities[name] == expected[name] for name in expected}
    if not all(regressions.values()):
        raise RuntimeError("E_MATRIX_REGRESSION_MISMATCH")

    eigenvalues, eigenvectors = eigh(kff, mff, driver="gvd", check_finite=True)
    positive = np.flatnonzero(np.isfinite(eigenvalues) & (eigenvalues > 0.0))
    if positive.size == 0:
        raise RuntimeError("E_INITIAL_STATE_INVALID")
    mode = eigenvectors[:, int(positive[0])]
    phi = np.zeros(q.size, dtype=np.float64)
    phi[np.asarray(free, dtype=np.int64)] = mode
    y_position_dofs = [index for index in range(phi.size) if index % 6 == 1]
    measurement_dof = max(y_position_dofs, key=lambda index: abs(phi[index]))
    if phi[measurement_dof] < 0.0:
        phi *= -1.0
    y_position_scale = max(abs(phi[index]) for index in y_position_dofs)
    phi /= y_position_scale
    measurement_dof = max(y_position_dofs, key=lambda index: abs(phi[index]))
    measurement_node = measurement_dof // 6
    phi_path = output_dir / "phi1_normalized.txt"
    write_vector(phi_path, phi)
    static = json.loads((setup_dir / "static.json").read_text(encoding="utf-8"))
    setup = {
        "schema": "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_SETUP",
        "head": HEAD,
        "parent": PARENT,
        "physical_case": {
            "length_m": 50.0,
            "diameter_m": 1.0,
            "inner_diameter_m": 0.9,
            "elements": 16,
            "slices": 3,
            "slice_positions_m": [8.333333333333334, 25.0, 41.666666666666664],
            "youngs_modulus_Pa": 3227125779.2218256,
            "material_density_kg_m3": 26315.789473684214,
            "fluid_density_kg_m3": 1000.0,
            "gravity_m_s2": 9.81,
            "top_tension_N": 2179104.0029808935,
            "internal_gauss_order": 3,
            "mass_gauss_order": 5,
            "static_load_steps": 40,
            "static_relaxation": 0.8,
        },
        "static": static,
        "identities": identities,
        "expected_identities": expected,
        "regression_pass": regressions,
        "free_dof": {"count": len(free), "values": free, "sha256": identities["free_dof"]},
        "modal_setup": {
            "eigensolver": "scipy.linalg.eigh(K_ff, M_ff, driver='gvd', check_finite=True)",
            "lambda_1": float(eigenvalues[positive[0]]),
            "frequency_1_hz": float(math.sqrt(eigenvalues[positive[0]]) / (2.0 * math.pi)),
            "phi1_normalized_sha256": sha256_file(phi_path),
            "phi1_position_norm_sha256": sha256_array(phi),
            "measurement_node": measurement_node,
            "measurement_dof": measurement_dof,
            "measurement_component": "y_position",
            "normalization": "max_abs_full_y_position_component_equals_1",
            "sign": "measurement_component_positive",
        },
        "initial_condition": {
            "amplitude_m": 1.0e-4,
            "q0_definition": "q_static + amplitude * phi1_normalized",
            "qdot0_definition": "zero",
            "qddot0_definition": "production_initial_force_balance_on_dynamic_free_dofs",
        },
        "reference": {
            "matlab_sha256": REFERENCE_SHA,
            "frequency_hz": F_REF,
            "omega_rad_s": OMEGA_REF,
            "period_s": T_REF,
        },
        "time_contract": {
            "dt_s": DT,
            "steps": STEPS,
            "duration_s": 12.0 * T_REF,
            "newmark_beta": 0.25,
            "newmark_gamma": 0.5,
            "dynamic_newton_tolerance": 1.0e-8,
            "max_newton": 40,
        },
        "damping": {"mode": "none", "alpha": 0.0, "beta": 0.0},
        "protocol_sha256": protocol_sha,
    }
    write_json_atomic(output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_SETUP.json", setup)
    print(json.dumps(setup, indent=2, sort_keys=True))


def crossings_and_periods(time: np.ndarray, signal: np.ndarray) -> tuple[list[float], list[tuple[float, float, float]]]:
    crossings: list[float] = []
    for index in range(1, len(signal)):
        y0, y1 = float(signal[index - 1]), float(signal[index])
        if y0 < 0.0 <= y1 and y1 != y0:
            t0, t1 = float(time[index - 1]), float(time[index])
            crossings.append(t0 + (-y0) * (t1 - t0) / (y1 - y0))
    intervals: list[tuple[float, float, float]] = []
    lower, upper = 2.0 * T_REF, 12.0 * T_REF
    for left, right in zip(crossings, crossings[1:]):
        if left >= lower and right <= upper:
            intervals.append((left, right, right - left))
    return crossings, intervals


def peaks(time: np.ndarray, signal: np.ndarray) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    absolute = np.abs(signal)
    for index in range(1, len(signal) - 1):
        if absolute[index] >= absolute[index - 1] and absolute[index] >= absolute[index + 1]:
            result.append((float(time[index]), float(absolute[index])))
    return result


def analyze(setup_path: Path, output_dir: Path, protocol_sha: str) -> None:
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    rows = []
    crossing_rows = []
    peak_rows = []
    diag_rows = []
    for label in DT:
        history_path = output_dir / f"E_DT_{label}_HISTORY.csv"
        history = read_history(history_path)
        time = np.asarray(history["time"], dtype=np.float64)
        signal = np.asarray(history["displacement_rel_qstatic"], dtype=np.float64)
        velocity = np.asarray(history["velocity"], dtype=np.float64)
        crossings, intervals = crossings_and_periods(time, signal)
        period = float(np.mean([item[2] for item in intervals])) if intervals else float("nan")
        measured = 1.0 / period if math.isfinite(period) and period > 0.0 else float("nan")
        f_nm = (2.0 / DT[label]) * math.atan(OMEGA_REF * DT[label] / 2.0) / (2.0 * math.pi)
        e_f = abs(measured - F_REF) / F_REF if math.isfinite(measured) else float("nan")
        e_nm = abs(measured - f_nm) / F_REF if math.isfinite(measured) else float("nan")
        peak_values = peaks(time, signal)
        selected_peaks = [(t, a) for t, a in peak_values if t >= 2.0 * T_REF]
        early_values = [a for _, a in selected_peaks[:3]]
        late_values = [a for _, a in selected_peaks[-3:]]
        early = float(np.mean(early_values)) if len(early_values) == 3 else float("nan")
        late = float(np.mean(late_values)) if len(late_values) == 3 else float("nan")
        drift = abs(late - early) / early if math.isfinite(early) and early != 0.0 else float("nan")
        for number, value in enumerate(crossings, start=1):
            crossing_rows.append({"dt_label": label, "crossing_index": number, "time_s": value})
        for number, (t, value) in enumerate(selected_peaks, start=1):
            peak_rows.append({"dt_label": label, "peak_index": number, "time_s": t, "abs_amplitude_m": value})
        diag_rows.append({
            "dt_label": label,
            "history_sha256": sha256_file(history_path),
            "sample_count": len(time),
            "first_time_s": float(time[0]),
            "last_time_s": float(time[-1]),
            "all_converged": bool(np.all(np.asarray(history["converged"]) == 1)),
            "all_finite": bool(np.all(np.asarray(history["finite"]) == 1)),
            "max_newton_iterations": int(np.max(history["iterations"])),
            "mean_newton_iterations": float(np.mean(history["iterations"][1:])),
            "max_residual": float(np.max(history["residual"])),
            "max_normalized_residual": float(np.max(history["normalized_residual"])),
            "max_constraint_error": float(np.max(history["constraint_error"])),
            "max_abs_displacement_m": float(np.max(np.abs(signal))),
            "crossing_count": len(crossings),
            "selected_interval_count": len(intervals),
            "early_peak_count": len(early_values),
            "late_peak_count": len(late_values),
        })
        rows.append({
            "dt_label": label,
            "dt_s": DT[label],
            "steps": STEPS[label],
            "duration_s": float(time[-1]),
            "f_ref_hz": F_REF,
            "period_measured_s": period,
            "f_measured_hz": measured,
            "e_f": e_f,
            "f_newmark_hz": f_nm,
            "e_nm": e_nm,
            "early_amplitude_m": early,
            "late_amplitude_m": late,
            "e_amp": drift,
            "crossing_count": len(crossings),
            "selected_interval_count": len(intervals),
        })

    order_values = {}
    errors = [row["e_f"] for row in rows]
    for left, right in zip(rows, rows[1:]):
        order_values[f"p_{left['dt_label']}_{right['dt_label']}"] = math.log(left["e_f"] / right["e_f"], 2.0)
    orders = list(order_values.values())
    frequency_gate = math.isfinite(rows[-1]["e_f"]) and rows[-1]["e_f"] <= 2.0e-5
    monotonic_gate = all(errors[i] > errors[i + 1] for i in range(len(errors) - 1))
    order_gate = sum(1 for value in orders if 1.8 <= value <= 2.2) >= 2
    newmark_gate = all(math.isfinite(row["e_nm"]) and row["e_nm"] <= 1.0e-5 for row in rows[1:])
    amplitude_gate = math.isfinite(rows[-1]["e_amp"]) and rows[-1]["e_amp"] <= 5.0e-4
    dynamics_gate = all(item["all_converged"] and item["all_finite"] for item in diag_rows)
    constraint_gate = all(item["max_constraint_error"] <= 1.0e-12 for item in diag_rows)
    all_finite = all(math.isfinite(float(value)) for row in rows for value in row.values() if isinstance(value, (float, int)))
    gates = {
        "dynamic_steps": dynamics_gate,
        "finite": all_finite,
        "frequency": frequency_gate,
        "monotonic_refinement": monotonic_gate,
        "second_order": order_gate,
        "newmark_dispersion": newmark_gate,
        "amplitude_drift": amplitude_gate,
        "constraint": constraint_gate,
    }
    final_status = "PASS" if all(gates.values()) else "FAIL"
    first_failure = "" if final_status == "PASS" else next(
        name for name, passed in [
            ("E_DYNAMIC_STEP_FAIL", dynamics_gate),
            ("E_NONFINITE_RESULT", all_finite),
            ("E_FREQUENCY_FAIL", frequency_gate),
            ("E_TEMPORAL_CONVERGENCE_FAIL", monotonic_gate and order_gate),
            ("E_NEWMARK_DISPERSION_FAIL", newmark_gate),
            ("E_AMPLITUDE_DRIFT_FAIL", amplitude_gate),
            ("E_CONSTRAINT_FAIL", constraint_gate),
        ] if not passed
    )

    with (output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_DT_SUMMARY.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_CROSSINGS.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dt_label", "crossing_index", "time_s"])
        writer.writeheader()
        writer.writerows(crossing_rows)
    with (output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_PEAKS.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dt_label", "peak_index", "time_s", "abs_amplitude_m"])
        writer.writeheader()
        writer.writerows(peak_rows)
    with (output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_DIAGNOSTICS.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(diag_rows[0].keys()))
        writer.writeheader()
        writer.writerows(diag_rows)

    snapshot = {
        "schema": "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_EVIDENCE_SNAPSHOT",
        "protocol_sha256": protocol_sha,
        "setup_sha256": sha256_file(setup_path),
        "setup": setup,
        "dt_summary": rows,
        "diagnostics": diag_rows,
        "observed_orders": order_values,
        "gates": gates,
        "numerical_rerun": True,
        "energy_diagnostic": "NOT_AVAILABLE_PRODUCTION_API",
    }
    write_json_atomic(output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_EVIDENCE_SNAPSHOT.json", snapshot)

    result = {
        "status": final_status,
        "primary": first_failure,
        "baseline": {"head": HEAD, "parent": PARENT},
        "predecessor_statuses_retained": {
            "historical_older_E": "FAIL",
            "historical_E_V1_2": "PASS",
            "historical_reconstruction_attempt": "STOPPED_BEFORE_PROTOCOL / E_TEMPORAL_CONTRACT_INSUFFICIENT",
        },
        "protocol_sha256": protocol_sha,
        "setup_sha256": sha256_file(setup_path),
        "reference_sha256": REFERENCE_SHA,
        "physical_case": setup["physical_case"],
        "identities": setup["identities"],
        "phi1": setup["modal_setup"],
        "initial_condition": setup["initial_condition"],
        "reference": setup["reference"],
        "time_contract": setup["time_contract"],
        "dt_summary": rows,
        "observed_orders": order_values,
        "diagnostics": diag_rows,
        "gates": gates,
        "zero_damping": True,
        "energy_diagnostic": "NOT_AVAILABLE_PRODUCTION_API",
        "numerical_rerun": True,
        "artifact_evidence_written_before_gate": True,
    }
    write_json_atomic(output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_RESULT.json", result)
    report_lines = [
        "# ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1",
        "",
        f"Final status: `{final_status}`",
        f"Primary: `{first_failure or 'NONE'}`",
        "",
        "This is a new current-line replacement validation, not historical E V1.2.",
        "Historical older E FAIL, historical E V1.2 PASS, and the stopped reconstruction attempt are retained.",
        "",
        "## DT summary",
        "",
        "| label | dt (s) | measured f (Hz) | e_f | f_NM (Hz) | e_NM | e_amp |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report_lines.append(
            f"| {row['dt_label']} | {row['dt_s']:.17g} | {row['f_measured_hz']:.17g} | "
            f"{row['e_f']:.17g} | {row['f_newmark_hz']:.17g} | {row['e_nm']:.17g} | {row['e_amp']:.17g} |"
        )
    report_lines += ["", "## Observed orders", "", "```json", json.dumps(order_values, indent=2), "```", "", "## Gates", "", "```json", json.dumps(gates, indent=2), "```", ""]
    (output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")
    raw = [
        f"status {final_status}",
        f"primary {first_failure}",
        f"protocol_sha256 {protocol_sha}",
        f"reference_sha256 {REFERENCE_SHA}",
        f"f_ref_hz {F_REF:.17g}",
        f"T_ref_s {T_REF:.17g}",
        f"A_over_L {1.0e-4 / 50.0:.17g}",
        f"zero_damping mode none alpha 0 beta 0",
    ]
    for row in rows:
        raw.append(json.dumps(row, sort_keys=True))
    raw.append(f"observed_orders {json.dumps(order_values, sort_keys=True)}")
    raw.append(f"gates {json.dumps(gates, sort_keys=True)}")
    (output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_RAW.txt").write_text("\n".join(raw) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if final_status != "PASS":
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "analyze"])
    parser.add_argument("--setup-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--protocol-sha", required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.setup_dir, args.output_dir, args.protocol_sha)
    else:
        analyze(args.output_dir / "ANCF_FREE_VIBRATION_TEMPORAL_CURRENT_LINE_REPLACEMENT_V1_SETUP.json", args.output_dir, args.protocol_sha)


if __name__ == "__main__":
    main()
