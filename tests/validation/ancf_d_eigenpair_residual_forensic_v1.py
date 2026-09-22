import csv
import hashlib
import json
import math
import pathlib
import sys

import numpy as np
import scipy.linalg


ROOT = pathlib.Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "runtime" / "ANCF_validation"
OUT = EVIDENCE
NMODES = 6
RESIDUAL_FLOOR = 1.0e-300
JACOBI_TOL = 1.0e-12
JACOBI_MAX_FACTOR = 100


def read_matrix(path):
    return np.loadtxt(path, dtype=np.float64)


def read_vector(path):
    return np.loadtxt(path, dtype=np.float64)


def cpp_matmul(left, right):
    result = np.zeros((left.shape[0], right.shape[1]), dtype=np.float64)
    for row in range(left.shape[0]):
        for mid in range(left.shape[1]):
            for col in range(right.shape[1]):
                result[row, col] += left[row, mid] * right[mid, col]
    return result


def cpp_cholesky(matrix):
    n = matrix.shape[0]
    lower = np.zeros_like(matrix)
    for row in range(n):
        for col in range(row + 1):
            value = float(matrix[row, col])
            for k in range(col):
                value -= lower[row, k] * lower[col, k]
            if row == col:
                if not math.isfinite(value) or value <= 0.0:
                    raise RuntimeError("non-positive Cholesky pivot")
                lower[row, col] = math.sqrt(value)
            else:
                lower[row, col] = value / lower[col, col]
    return lower


def cpp_inverse_lower(lower):
    n = lower.shape[0]
    inverse = np.zeros_like(lower)
    for col in range(n):
        for row in range(n):
            value = 1.0 if row == col else 0.0
            for k in range(row):
                value -= lower[row, k] * inverse[k, col]
            inverse[row, col] = value / lower[row, row]
    return inverse


def cpp_jacobi(matrix):
    work = np.array(matrix, dtype=np.float64, copy=True)
    n = work.shape[0]
    vectors = np.eye(n, dtype=np.float64)
    scale = 1.0
    for value in work.ravel():
        scale = max(scale, abs(float(value)))
    max_iterations = JACOBI_MAX_FACTOR * n * n
    for iteration in range(max_iterations):
        p = 0
        q = 1
        maximum = 0.0
        for row in range(n):
            for col in range(row + 1, n):
                if abs(float(work[row, col])) > maximum:
                    maximum = abs(float(work[row, col]))
                    p = row
                    q = col
        if maximum <= JACOBI_TOL * scale:
            order = sorted(range(n), key=lambda index: float(work[index, index]))
            values = np.array([work[index, index] for index in order], dtype=np.float64)
            ordered_vectors = vectors[:, order].copy()
            offdiag = work - np.diag(np.diag(work))
            return {
                "values": values,
                "vectors": ordered_vectors,
                "raw_vectors": vectors.copy(),
                "raw_matrix": work.copy(),
                "termination_iteration": iteration,
                "sweeps": iteration,
                "max_offdiag": maximum,
                "offdiag_frobenius": float(np.linalg.norm(offdiag, ord="fro")),
                "matrix_frobenius": float(np.linalg.norm(work, ord="fro")),
                "diagonal_scale": float(np.max(np.abs(np.diag(work)))),
                "scale": scale,
                "threshold": JACOBI_TOL * scale,
            }
        app = float(work[p, p])
        aqq = float(work[q, q])
        apq = float(work[p, q])
        angle = 0.5 * math.atan2(2.0 * apq, aqq - app)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        for index in range(n):
            if index == p or index == q:
                continue
            aip = float(work[index, p])
            aiq = float(work[index, q])
            work[index, p] = work[p, index] = cosine * aip - sine * aiq
            work[index, q] = work[q, index] = sine * aip + cosine * aiq
        work[p, p] = cosine * cosine * app - 2.0 * sine * cosine * apq + sine * sine * aqq
        work[q, q] = sine * sine * app + 2.0 * sine * cosine * apq + cosine * cosine * aqq
        work[p, q] = work[q, p] = 0.0
        for index in range(n):
            vip = float(vectors[index, p])
            viq = float(vectors[index, q])
            vectors[index, p] = cosine * vip - sine * viq
            vectors[index, q] = sine * vip + cosine * viq
    raise RuntimeError("Jacobi did not converge")


def dot(x, y):
    total = 0.0
    for left, right in zip(x, y):
        total += float(left) * float(right)
    return total


def norm2(x):
    return math.sqrt(dot(x, x))


def action_metrics(mass, stiffness, phi, lam):
    left = stiffness @ phi
    right = mass @ phi
    residual = left - lam * right
    residual_norm = float(np.linalg.norm(residual))
    action = max(float(np.linalg.norm(left)), abs(lam) * float(np.linalg.norm(right)), RESIDUAL_FLOOR)
    generalized = residual_norm / action
    backward = residual_norm / ((float(np.linalg.norm(stiffness, 2)) + abs(lam) * float(np.linalg.norm(mass, 2))) * float(np.linalg.norm(phi)))
    rayleigh = float(phi @ stiffness @ phi) / float(phi @ mass @ phi)
    rayleigh_error = abs(rayleigh - lam) / max(abs(lam), RESIDUAL_FLOOR)
    m_norm = float(phi @ mass @ phi)
    return {
        "residual_norm": residual_norm,
        "action_normalized": generalized,
        "backward_error": backward,
        "rayleigh_lambda": rayleigh,
        "rayleigh_relative_error": rayleigh_error,
        "m_norm": m_norm,
        "left_norm": float(np.linalg.norm(left)),
        "lambda_mphi_norm": abs(lam) * float(np.linalg.norm(right)),
    }


def transformed_metrics(a, y, lam):
    residual = a @ y - lam * y
    residual_norm = float(np.linalg.norm(residual))
    action = max(float(np.linalg.norm(a @ y)), abs(lam) * float(np.linalg.norm(y)), RESIDUAL_FLOOR)
    backward = residual_norm / ((float(np.linalg.norm(a, 2)) + abs(lam)) * float(np.linalg.norm(y)))
    return {"residual_norm": residual_norm, "action_normalized": residual_norm / action, "backward_error": backward}


def longdouble_action_metrics(mass, stiffness, phi, lam):
    md = np.asarray(mass, dtype=np.longdouble)
    kd = np.asarray(stiffness, dtype=np.longdouble)
    pd = np.asarray(phi, dtype=np.longdouble)
    ld = np.longdouble(lam)
    residual = kd @ pd - ld * (md @ pd)
    return float(np.sqrt(np.sum(residual * residual)))


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    m = read_matrix(EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_M_FF.txt")
    k = read_matrix(EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_K_FF.txt")
    q = read_vector(EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_Q.txt")
    free = [int(line.strip()) for line in (EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_FREE_DOF.txt").read_text().splitlines() if line.strip()]
    expected = {
        "q": "0DCFA5E840B9C79D39091C99EB0C399DFABD4507811F2A63E77C196A6095E385",
        "m": "7A6C2133F4814411D9B39900017A068D066A0AD9679DBAA2CFDBF7EC38C3CEA1",
        "k": "7759CAB46444A7100CF6B915BA091D4C9B98F3FA8C5136E514FCD626C41E997E",
        "free": "522727C180A9ACDAB071B06819FC476EA790603931B99F5FF6F432E404C60D71",
    }
    actual = {
        "q": sha256_file(EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_Q.txt"),
        "m": sha256_file(EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_M_FF.txt"),
        "k": sha256_file(EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_K_FF.txt"),
        "free": sha256_file(EVIDENCE / "ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1_FREE_DOF.txt"),
    }
    if actual != expected:
        raise RuntimeError(f"D_FORENSIC_V1_1_EVIDENCE_MISMATCH: {actual} != {expected}")

    lower = cpp_cholesky(m)
    inverse = cpp_inverse_lower(lower)
    a = cpp_matmul(cpp_matmul(inverse, k), inverse.T)
    jacobi = cpp_jacobi(a)
    lam_j = jacobi["values"][:NMODES]
    y_j = jacobi["vectors"][:, :NMODES]
    phi_j = np.zeros_like(y_j)
    for col in range(NMODES):
        phi_j[:, col] = cpp_matmul(inverse.T, y_j[:, col:col + 1]).ravel()
        mass_norm = math.sqrt(dot(phi_j[:, col], m @ phi_j[:, col]))
        phi_j[:, col] /= mass_norm

    reference = np.array([
        0.19876102675389518, 0.476181930710043, 0.8702401692325742,
        1.3985123281821055, 2.068594917195311, 2.8842837351244612])
    modes = []
    for i in range(NMODES):
        metrics = action_metrics(m, k, phi_j[:, i], float(lam_j[i]))
        standard_metrics = transformed_metrics(a, y_j[:, i], float(lam_j[i]))
        modes.append({
            "mode": i + 1,
            "lambda_jacobi": float(lam_j[i]),
            "frequency_jacobi_hz": float(math.sqrt(lam_j[i]) / (2.0 * math.pi)),
            "frequency_reference_hz": float(reference[i]),
            "frequency_relative_error_jacobi": float(abs(math.sqrt(lam_j[i]) / (2.0 * math.pi) - reference[i]) / reference[i]),
            **metrics,
            "transformed": standard_metrics,
            "high_precision_residual_norm": longdouble_action_metrics(m, k, phi_j[:, i], float(lam_j[i])),
        })

    # Independent LAPACK-backed generalized symmetric eigensolver.
    lam_i, phi_i = scipy.linalg.eigh(k, m, driver="gvd", check_finite=True)
    independent = []
    for i in range(NMODES):
        metrics = action_metrics(m, k, phi_i[:, i], float(lam_i[i]))
        independent.append({
            "mode": i + 1,
            "lambda": float(lam_i[i]),
            "frequency_hz": float(math.sqrt(lam_i[i]) / (2.0 * math.pi)),
            "difference_vs_jacobi_hz": float(math.sqrt(lam_i[i]) / (2.0 * math.pi) - modes[i]["frequency_jacobi_hz"]),
            "difference_vs_matlab_hz": float(math.sqrt(lam_i[i]) / (2.0 * math.pi) - reference[i]),
            **metrics,
        })

    gram_j = phi_j.T @ m @ phi_j
    gram_i = phi_i[:, :NMODES].T @ m @ phi_i[:, :NMODES]
    result = {
        "classification": "D_VALIDATION_JACOBI_PRECISION_LIMIT",
        "secondary_contributor": "D_CHOLESKY_BACKTRANSFORM_CONDITIONING_EFFECT",
        "status_semantics": {
            "D_historical": "PASS",
            "D_current_line_V1": "FAIL:D_MODAL_FREQUENCY_FAIL",
            "D_current_line_V1_1": "FAIL:D_EIGENPAIR_RESIDUAL_FAIL",
            "D_status_changed": False,
            "D_V1_2_executed": False,
        },
        "baseline": {
            "head": "36927c01208339f179670322799eb84d86dd2992",
            "parent": "b5e22a2fdba5961dabc2ed62a9d833f6bf649c5a",
        },
        "matrix_identity": {"expected": expected, "actual": actual, "match": True},
        "jacobi_contract": {
            "cholesky": "M=L L^T",
            "standard_problem": "A=L^-1 K L^-T",
            "explicit_symmetrization": False,
            "rotation": "angle=0.5*atan2(2*apq,aqq-app)",
            "stopping": "max absolute off-diagonal <= 1e-12*max(1,max(abs(A_ij)))",
            "tolerance": JACOBI_TOL,
            "max_iterations": JACOBI_MAX_FACTOR * m.shape[0] * m.shape[0],
            "sorting": "ascending final diagonal",
            "back_transform": "phi=L^-T y",
            "m_normalization": True,
            "residual_contract": "action-normalized generalized residual",
        },
        "conditioning": {
            "M_ff_cond_2": float(np.linalg.cond(m, 2)),
            "K_ff_cond_2": float(np.linalg.cond(k, 2)),
            "L_cond_2": float(np.linalg.cond(lower, 2)),
            "A_cond_2": float(np.linalg.cond(a, 2)),
            "M_frobenius": float(np.linalg.norm(m, "fro")),
            "K_frobenius": float(np.linalg.norm(k, "fro")),
            "A_frobenius": float(np.linalg.norm(a, "fro")),
        },
        "jacobi_termination": {key: float(value) if isinstance(value, (float, np.floating)) else int(value) for key, value in jacobi.items() if key not in ("values", "vectors", "raw_vectors", "raw_matrix")},
        "modes": modes,
        "independent_solver": {
            "identity": "scipy.linalg.eigh generalized symmetric LAPACK driver=gvd",
            "scipy_version": scipy.__version__,
            "numpy_version": np.__version__,
            "m_orthogonality_frobenius": float(np.linalg.norm(gram_i - np.eye(NMODES), "fro")),
            "modes": independent,
        },
        "orthogonality": {
            "jacobi_m_phi_minus_I_frobenius": float(np.linalg.norm(gram_j - np.eye(NMODES), "fro")),
            "independent_m_phi_minus_I_frobenius": float(np.linalg.norm(gram_i - np.eye(NMODES), "fro")),
        },
        "reference_hz": reference.tolist(),
        "forensic_rerun": False,
        "production_source_modified": False,
    }
    write_json(OUT / "ANCF_D_EIGENPAIR_RESIDUAL_FORENSIC_V1_RESULT.json", result)
    write_json(OUT / "ANCF_D_EIGENPAIR_RESIDUAL_FORENSIC_V1_CONDITIONING.json", {
        "classification": result["classification"],
        "conditioning": result["conditioning"],
        "jacobi_termination": result["jacobi_termination"],
        "matrix_identity": result["matrix_identity"],
        "forensic_rerun": False,
    })
    with (OUT / "ANCF_D_EIGENPAIR_RESIDUAL_FORENSIC_V1_MODES.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["mode", "reference_hz", "jacobi_hz", "independent_hz", "jacobi_relative_error", "independent_relative_error", "jacobi_action_residual", "jacobi_backward_error", "transformed_action_residual", "transformed_backward_error", "rayleigh_relative_error", "independent_action_residual", "independent_backward_error", "high_precision_residual_norm"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for j, ind in zip(modes, independent):
            writer.writerow({
                "mode": j["mode"], "reference_hz": j["frequency_reference_hz"], "jacobi_hz": j["frequency_jacobi_hz"], "independent_hz": ind["frequency_hz"],
                "jacobi_relative_error": j["frequency_relative_error_jacobi"], "independent_relative_error": abs(ind["difference_vs_matlab_hz"]) / j["frequency_reference_hz"],
                "jacobi_action_residual": j["action_normalized"], "jacobi_backward_error": j["backward_error"],
                "transformed_action_residual": j["transformed"]["action_normalized"], "transformed_backward_error": j["transformed"]["backward_error"],
                "rayleigh_relative_error": j["rayleigh_relative_error"], "independent_action_residual": ind["action_normalized"],
                "independent_backward_error": ind["backward_error"], "high_precision_residual_norm": j["high_precision_residual_norm"],
            })
    audit = """# Eigensolver audit\n\nThe V1.1 source uses lower Cholesky `M=L L^T`, explicit `A=L^-1 K L^-T`, no separate symmetrization, largest-absolute-off-diagonal Jacobi pivots, angle `0.5*atan2(2*apq,aqq-app)`, stopping `max_offdiag <= 1e-12*max(1,max(abs(A)))`, max iterations `100*n*n`, ascending diagonal sorting, `phi=L^-T y`, M normalization, and action-normalized residuals.\n\nThe forensic reconstruction executed the same arithmetic on the persisted M_ff/K_ff package only. No production case or static solve was rerun. The independent cross-check was SciPy/LAPACK `scipy.linalg.eigh(K_ff,M_ff,driver='gvd')`.\n\nThe full numerical termination and cross-check data are in the JSON, conditioning JSON, and modes CSV.\n"""
    (OUT / "ANCF_D_EIGENPAIR_RESIDUAL_FORENSIC_V1_EIGENSOLVER_AUDIT.md").write_text(audit, encoding="utf-8")
    raw = {
        "matrix_identity": result["matrix_identity"],
        "classification": result["classification"],
        "jacobi_termination": result["jacobi_termination"],
        "independent_solver": result["independent_solver"]["identity"],
        "forensic_rerun": False,
    }
    (OUT / "ANCF_D_EIGENPAIR_RESIDUAL_FORENSIC_V1_RAW.txt").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
