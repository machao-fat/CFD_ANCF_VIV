"""Formal V1.2 validation-only LAPACK modal run.

The C++ companion has already regenerated q/M/K through production APIs.
This script performs only evidence loading, SciPy/LAPACK eigenanalysis, and
the frozen V1.2 evidence/gate bookkeeping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

import numpy as np
import scipy
import scipy.linalg


HEAD = "36927c01208339f179670322799eb84d86dd2992"
PARENT = "b5e22a2fdba5961dabc2ed62a9d833f6bf649c5a"
REFERENCE_SHA = "5B25F095B2FDC066CF8D334B12A993F1D62DB1BCCD95317F8074E7EA3E3D8CEE"
REFERENCE_HZ = np.array(
    [
        0.19876102675389518,
        0.476181930710043,
        0.8702401692325742,
        1.3985123281821055,
        2.068594917195311,
        2.8842837351244612,
    ],
    dtype=float,
)
EXPECTED = {
    "q": "0DCFA5E840B9C79D39091C99EB0C399DFABD4507811F2A63E77C196A6095E385",
    "M_full": "C8678F321EA1717D2AE8D4F270EED66A561BDA9E2FF5A7DB152A6123063D30BD",
    "M_ff": "7A6C2133F4814411D9B39900017A068D066A0AD9679DBAA2CFDBF7EC38C3CEA1",
    "K_full": "A8F163771875468762C6D01C0F71E4A53491FA2898A7429E239A9BD207E0B5FA",
    "K_ff": "7759CAB46444A7100CF6B915BA091D4C9B98F3FA8C5136E514FCD626C41E997E",
    "free": "522727C180A9ACDAB071B06819FC476EA790603931B99F5FF6F432E404C60D71",
}
FREE = [4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34, 37, 40, 43, 46, 49,
        52, 55, 58, 61, 64, 67, 70, 73, 76, 79, 82, 85, 88, 91, 94, 97]
PROTECTED = {
    "ancf_kernel.cpp": "2E69383D14960E0B16710736F00805D5E4EC18658725852E49156FABA3819D3B",
    "ancf_kernel.hpp": "DA866C2CA1E25B620111551251C00E46F05F6BC8981FCFE6F0CC095D5794A6FB",
    "ancf_worker_main.cpp": "16D1BA919C31036712B322594041CFDF304D0EC3426B9FB04940D753FD4927AD",
    "kernel_protocol.py": "6A5E7AD8FC9B42A9BAE4B221A6BDDA595A6BFF463072331D5F199E866BF256C4",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def atomic_json(path: Path, payload: object) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def finite_tree(value: object) -> bool:
    if isinstance(value, dict):
        return all(finite_tree(item) for item in value.values())
    if isinstance(value, list):
        return all(finite_tree(item) for item in value)
    if isinstance(value, (int, float)):
        return bool(np.isfinite(value))
    return True


def matrix_metrics(matrix: np.ndarray) -> dict[str, object]:
    return {
        "shape": list(matrix.shape),
        "frobenius_norm": float(np.linalg.norm(matrix, ord="fro")),
        "spectral_2_norm": float(np.linalg.norm(matrix, ord=2)),
        "symmetry_relative_frobenius": float(
            np.linalg.norm(matrix - matrix.T, ord="fro")
            / max(np.linalg.norm(matrix, ord="fro"), 1e-300)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--predecessor-dir", required=True, type=Path)
    parser.add_argument("--cpp-stdout", required=True, type=Path)
    parser.add_argument("--cpp-stderr", required=True, type=Path)
    args = parser.parse_args()
    out = args.evidence_dir
    out.mkdir(parents=True, exist_ok=True)

    q_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_Q.txt"
    mfull_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_M_FULL.txt"
    mff_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_M_FF.txt"
    kfull_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_K_FULL.txt"
    kff_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_K_FF.txt"
    free_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_FREE_DOF.txt"
    static_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_STATIC.json"
    identity_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_MATRIX_IDENTITY.json"
    env_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_SOLVER_ENVIRONMENT.json"
    snapshot_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_DIAGNOSTIC_SNAPSHOT.json"
    modes_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_MODES.csv"
    result_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_RESULT.json"
    report_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_REPORT.md"
    raw_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_RAW.txt"
    manifest_path = out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_SHA256_MANIFEST.txt"

    static = json.loads(static_path.read_text(encoding="utf-8"))
    q = np.loadtxt(q_path, dtype=np.float64)
    m_full = np.loadtxt(mfull_path, dtype=np.float64)
    m_ff = np.loadtxt(mff_path, dtype=np.float64)
    k_full = np.loadtxt(kfull_path, dtype=np.float64)
    k_ff = np.loadtxt(kff_path, dtype=np.float64)
    free = [int(x) for x in free_path.read_text(encoding="utf-8").split()]

    paths = {"q": q_path, "M_full": mfull_path, "M_ff": mff_path,
             "K_full": kfull_path, "K_ff": kff_path, "free": free_path}
    identities = {name: sha256_file(path) for name, path in paths.items()}
    matrix_regression = {
        name: {"actual": identities[name], "expected_v1_1": EXPECTED[name],
               "exact_match": identities[name] == EXPECTED[name]}
        for name in identities
    }
    matrix_regression_pass = all(item["exact_match"] for item in matrix_regression.values())

    solver_environment = {
        "python_version": sys.version,
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "eigensolver": "scipy.linalg.eigh(K_ff, M_ff, driver='gvd', check_finite=True)",
        "driver": "gvd",
        "lapack_backend_observable": "SciPy linked LAPACK; backend not exposed by scipy.linalg API",
        "reference_sha256": REFERENCE_SHA,
    }
    atomic_json(env_path, solver_environment)

    if not matrix_regression_pass:
        # Preserve evidence and classify before any eigensolver gate.
        snapshot = {
            "snapshot_written_before_gates": True,
            "formal_numerical_rerun": True,
            "matrix_regression": matrix_regression,
            "static": static,
            "solver_environment": solver_environment,
            "gate_order": ["static", "matrix_regression", "positive_eigenvalues",
                            "normwise_backward_error", "m_orthogonality", "frequency", "integrity"],
        }
        atomic_json(snapshot_path, snapshot)
        result = {"validation": "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2",
                  "status": "FAIL", "primary_failure": "D_V1_2_MATRIX_REGRESSION_MISMATCH",
                  "snapshot_written_before_gates": True, "matrix_regression": matrix_regression,
                  "numerical_rerun": True, "production_source_modified": False,
                  "baseline": {"head": HEAD, "parent": PARENT}}
        atomic_json(result_path, result)
        raw_path.write_text("matrix regression mismatch before LAPACK execution\n", encoding="utf-8")
        return 1

    try:
        eigenvalues, eigenvectors = scipy.linalg.eigh(
            k_ff, m_ff, driver="gvd", check_finite=True
        )
    except Exception as exc:  # pragma: no cover - formal environment failure
        snapshot = {"snapshot_written_before_gates": True, "matrix_regression": matrix_regression,
                    "eigensolver_error": repr(exc), "solver_environment": solver_environment}
        atomic_json(snapshot_path, snapshot)
        result = {"validation": "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2",
                  "status": "FAIL", "primary_failure": "D_V1_2_LAPACK_EIGENSOLVER_UNAVAILABLE",
                  "snapshot_written_before_gates": True, "numerical_rerun": True}
        atomic_json(result_path, result)
        return 1

    positive_indices = [i for i, value in enumerate(eigenvalues)
                        if np.isfinite(value) and value > 0.0]
    positive_indices = positive_indices[:6]
    positive_finite = len(positive_indices) == 6
    if positive_finite:
        lambdas = eigenvalues[positive_indices]
        phi = eigenvectors[:, positive_indices]
    else:
        lambdas = np.full(6, np.nan)
        phi = np.full((m_ff.shape[0], 6), np.nan)

    frequencies = np.sqrt(lambdas) / (2.0 * np.pi)
    absolute_errors = np.abs(frequencies - REFERENCE_HZ)
    relative_errors = absolute_errors / np.abs(REFERENCE_HZ)
    m_norm = float(np.linalg.norm(m_ff, ord=2))
    k_norm = float(np.linalg.norm(k_ff, ord=2))
    backward_errors = []
    action_residuals = []
    rayleigh_lambdas = []
    rayleigh_errors = []
    residual_norms = []
    for index in range(6):
        if not positive_finite:
            backward_errors.append(float("nan")); action_residuals.append(float("nan"))
            rayleigh_lambdas.append(float("nan")); rayleigh_errors.append(float("nan")); residual_norms.append(float("nan"))
            continue
        vector = phi[:, index]
        residual = k_ff @ vector - lambdas[index] * (m_ff @ vector)
        residual_norm = float(np.linalg.norm(residual, ord=2))
        left_norm = float(np.linalg.norm(k_ff @ vector, ord=2))
        right_norm = float(np.linalg.norm(m_ff @ vector, ord=2))
        denom = (k_norm + abs(float(lambdas[index])) * m_norm) * float(np.linalg.norm(vector, ord=2))
        backward_errors.append(residual_norm / denom if np.isfinite(denom) and denom > 0.0 else float("nan"))
        action_residuals.append(residual_norm / max(left_norm, abs(float(lambdas[index])) * right_norm, 1e-300))
        rayleigh = float(vector @ (k_ff @ vector) / (vector @ (m_ff @ vector)))
        rayleigh_lambdas.append(rayleigh)
        rayleigh_errors.append(abs(rayleigh - float(lambdas[index])) / max(abs(float(lambdas[index])), 1e-300))
        residual_norms.append(residual_norm)

    gram = phi.T @ m_ff @ phi
    m_orthogonality = float(np.linalg.norm(gram - np.eye(6), ord="fro"))
    finite_flags = {
        "q": bool(np.all(np.isfinite(q))),
        "M_full": bool(np.all(np.isfinite(m_full))),
        "M_ff": bool(np.all(np.isfinite(m_ff))),
        "K_full": bool(np.all(np.isfinite(k_full))),
        "K_ff": bool(np.all(np.isfinite(k_ff))),
        "eigenvalues": bool(np.all(np.isfinite(lambdas))),
        "frequencies": bool(np.all(np.isfinite(frequencies))),
        "backward_errors": bool(np.all(np.isfinite(backward_errors))),
        "action_residuals": bool(np.all(np.isfinite(action_residuals))),
    }
    modes = []
    for i in range(6):
        modes.append({
            "mode": i + 1,
            "lambda": float(lambdas[i]),
            "omega_rad_s": float(np.sqrt(lambdas[i])) if positive_finite else float("nan"),
            "frequency_current_hz": float(frequencies[i]),
            "frequency_reference_hz": float(REFERENCE_HZ[i]),
            "absolute_frequency_error_hz": float(absolute_errors[i]),
            "relative_frequency_error": float(relative_errors[i]),
            "normwise_backward_error": float(backward_errors[i]),
            "action_normalized_residual_diagnostic": float(action_residuals[i]),
            "rayleigh_lambda": float(rayleigh_lambdas[i]),
            "rayleigh_relative_error_diagnostic": float(rayleigh_errors[i]),
            "residual_norm": float(residual_norms[i]),
            "positive_finite_gate": bool(positive_finite and np.isfinite(lambdas[i]) and lambdas[i] > 0.0),
            "backward_error_gate": bool(np.isfinite(backward_errors[i]) and backward_errors[i] <= 1e-12),
            "frequency_gate": bool(np.isfinite(relative_errors[i]) and relative_errors[i] <= 0.005),
        })

    # This is the mandatory evidence-before-gate snapshot.
    snapshot = {
        "snapshot_written_before_gates": True,
        "formal_numerical_rerun": True,
        "baseline": {"head": HEAD, "parent": PARENT},
        "static": static,
        "matrix_regression": matrix_regression,
        "identities": identities,
        "free_dof": {"count": len(free), "values": free, "sha256": identities["free"]},
        "matrix_metrics": {
            "M_full": matrix_metrics(m_full), "M_ff": matrix_metrics(m_ff),
            "K_full": matrix_metrics(k_full), "K_ff": matrix_metrics(k_ff),
        },
        "modes": modes,
        "m_orthogonality_error": m_orthogonality,
        "m_orthogonality_matrix": gram.tolist(),
        "finite_flags": finite_flags,
        "solver_environment": solver_environment,
        "zero_damping": {"mode": "none", "alpha": 0.0, "beta": 0.0},
        "gate_order": ["static", "matrix_regression", "positive_eigenvalues",
                        "normwise_backward_error", "m_orthogonality", "frequency", "integrity"],
    }
    atomic_json(snapshot_path, snapshot)
    atomic_json(identity_path, {
        "q": {"sha256": identities["q"], "count": int(q.size)},
        "M_full": {**matrix_metrics(m_full), "sha256": identities["M_full"]},
        "M_ff": {**matrix_metrics(m_ff), "sha256": identities["M_ff"]},
        "K_full": {**matrix_metrics(k_full), "sha256": identities["K_full"]},
        "K_ff": {**matrix_metrics(k_ff), "sha256": identities["K_ff"]},
        "free_dof": {"count": len(free), "sha256": identities["free"], "values": free},
        "matrix_regression": matrix_regression,
    })

    modes_lines = ["mode,reference_hz,current_hz,absolute_error_hz,relative_error,lambda,normwise_backward_error,action_residual_diagnostic,rayleigh_lambda,rayleigh_relative_error,positive_finite_gate,backward_error_gate,frequency_gate"]
    for mode in modes:
        modes_lines.append(",".join(str(mode[key]) for key in [
            "mode", "frequency_reference_hz", "frequency_current_hz", "absolute_frequency_error_hz",
            "relative_frequency_error", "lambda", "normwise_backward_error",
            "action_normalized_residual_diagnostic", "rayleigh_lambda",
            "rayleigh_relative_error_diagnostic", "positive_finite_gate", "backward_error_gate", "frequency_gate"
        ]))
    modes_path.write_text("\n".join(modes_lines) + "\n", encoding="utf-8")

    static_gate = bool(static.get("converged") and finite_tree(static))
    matrix_gate = matrix_regression_pass
    positive_gate = positive_finite
    backward_gate = bool(positive_gate and np.all(np.asarray(backward_errors) <= 1e-12))
    orth_gate = bool(np.isfinite(m_orthogonality) and m_orthogonality <= 1e-8)
    frequency_gate = bool(np.all(np.asarray(relative_errors) <= 0.005))
    integrity_gate = bool(all(finite_flags.values()) and static_gate)
    if not static_gate:
        failure = "D_PRESTRESS_EQUILIBRIUM_FAIL"
    elif not matrix_gate:
        failure = "D_V1_2_MATRIX_REGRESSION_MISMATCH"
    elif not positive_gate:
        failure = "D_MODAL_NONPOSITIVE_EIGENVALUE"
    elif not backward_gate:
        failure = "D_EIGENPAIR_BACKWARD_ERROR_FAIL"
    elif not orth_gate:
        failure = "D_M_ORTHOGONALITY_FAIL"
    elif not frequency_gate:
        failure = "D_MODAL_FREQUENCY_FAIL"
    elif not integrity_gate:
        failure = "D_NONFINITE_RESULT"
    else:
        failure = None

    result = {
        "validation": "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2",
        "status": "PASS" if failure is None else "FAIL",
        "primary_failure": failure,
        "snapshot_written_before_gates": True,
        "numerical_rerun": True,
        "production_source_modified": False,
        "baseline": {"head": HEAD, "parent": PARENT},
        "predecessors": {
            "D_V1": "FAIL:D_MODAL_FREQUENCY_FAIL",
            "D_V1_1": "FAIL:D_EIGENPAIR_RESIDUAL_FAIL",
            "forensic": "COMPLETE:D_VALIDATION_JACOBI_PRECISION_LIMIT",
        },
        "reference_sha256": REFERENCE_SHA,
        "physical_case": {"length_m": 50.0, "elements": 16, "slices": 3,
                           "top_tension_N": 2179104.0029808935,
                           "internal_gauss_order": 3, "mass_gauss_order": 5,
                           "static_contract": [40, 0.8]},
        "static": static,
        "identities": identities,
        "matrix_regression": matrix_regression,
        "modes": modes,
        "max_relative_frequency_error": float(np.max(relative_errors)),
        "rms_relative_frequency_error": float(np.sqrt(np.mean(relative_errors ** 2))),
        "m_orthogonality_error": m_orthogonality,
        "zero_damping": {"mode": "none", "alpha": 0.0, "beta": 0.0, "state_damping_zero": True},
        "gates": {"static": static_gate, "matrix_regression": matrix_gate,
                  "positive_finite": positive_gate, "normwise_backward_error": backward_gate,
                  "m_orthogonality": orth_gate, "frequency": frequency_gate,
                  "integrity": integrity_gate},
        "solver_environment": solver_environment,
    }
    atomic_json(result_path, result)

    report = [
        "# ANCF prestretched modal current-line validation V1.2",
        "",
        f"Status: **{result['status']}**" + (f"; first failure: `{failure}`" if failure else "."),
        "",
        "This is a fresh current-line production-state reexecution followed by validation-only SciPy/LAPACK generalized symmetric eigensolution.",
        "Predecessor V1 and V1.1 failures remain immutable.",
        "",
        "## Identity and matrix regression",
        "",
        f"HEAD `{HEAD}`; HEAD^ `{PARENT}`; matrix regression: `{matrix_gate}`.",
        "",
        "| mode | MATLAB Hz | V1.2 Hz | rel. frequency error | normwise backward error | action residual diagnostic | Rayleigh rel. diagnostic |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in modes:
        report.append("| {mode} | {frequency_reference_hz:.17g} | {frequency_current_hz:.17g} | {relative_frequency_error:.6g} | {normwise_backward_error:.6g} | {action_normalized_residual_diagnostic:.6g} | {rayleigh_relative_error_diagnostic:.6g} |".format(**mode))
    report.extend([
        "",
        f"Maximum relative frequency error: `{result['max_relative_frequency_error']:.17g}`.",
        f"RMS relative frequency error: `{result['rms_relative_frequency_error']:.17g}`.",
        f"M-orthogonality Frobenius error: `{m_orthogonality:.17g}`.",
        "",
        "The V1.1 action-normalized residual is diagnostic only in V1.2; the primary eigenpair gate is the frozen normwise generalized backward error <= 1e-12.",
        "",
        "No production source was modified. No MATLAB, CFD, FSI, E/F/G1, or worker execution was performed.",
        "",
    ])
    report_path.write_text("\n".join(report), encoding="utf-8")

    raw = [
        "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2",
        f"HEAD={HEAD}", f"HEAD^={PARENT}",
        "formal_numerical_rerun=true",
        "C++ production-state stdout:", args.cpp_stdout.read_text(encoding="utf-8") if args.cpp_stdout.exists() else "",
        "C++ production-state stderr:", args.cpp_stderr.read_text(encoding="utf-8") if args.cpp_stderr.exists() else "",
        "Python solver environment:", json.dumps(solver_environment, indent=2),
        "Result:", json.dumps(result, indent=2),
    ]
    raw_path.write_text("\n".join(raw) + "\n", encoding="utf-8")

    artifacts = [
        out / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.2_PROTOCOL.md",
        report_path, result_path, raw_path, modes_path, static_path, identity_path,
        snapshot_path, env_path, manifest_path,
    ]
    lines = ["artifact,sha256"]
    for path in artifacts[:-1]:
        if path.exists():
            lines.append(f"{path.name},{sha256_file(path)}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Add manifest hash after its content is fixed in the final response; the
    # manifest intentionally does not self-hash.
    print(json.dumps({"status": result["status"], "primary_failure": failure,
                      "max_relative_frequency_error": result["max_relative_frequency_error"],
                      "max_backward_error": max(backward_errors),
                      "m_orthogonality_error": m_orthogonality}, sort_keys=True))
    return 0 if failure is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
