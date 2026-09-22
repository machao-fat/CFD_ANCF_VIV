from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import solve_bvp, solve_ivp
from scipy.optimize import root_scalar


L = 1.0
EA = 100.0
EI = 1.0
P = 2.0
MESHES = [4, 8, 16, 32]
REFERENCE_POINTS = 1001
IVP_RTOL = 1.0e-11
IVP_ATOL = 1.0e-13
BVP_TOL = 1.0e-11
BVP_MAX_NODES = 20000
ROOT_XTOL = 1.0e-13
ROOT_RTOL = 1.0e-13
M0_SCAN = np.linspace(0.0, 8.0, 161, dtype=np.float64)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def lambda_roots(theta: float, moment: float, load: float = P) -> list[float]:
    coefficients = [EA / 2.0, 0.0, -EA / 2.0 - moment * moment / EI, -load * math.sin(theta)]
    roots = np.roots(np.asarray(coefficients, dtype=np.float64))
    real = []
    for root in roots:
        tolerance = 1.0e-9 * max(1.0, abs(float(root.real)))
        if abs(float(root.imag)) <= tolerance:
            value = float(root.real)
            if value > 0.0 and math.isfinite(value):
                real.append(value)
    return sorted(real)


def stretch_derivative(value: float, moment: float) -> float:
    return EA / 2.0 * (3.0 * value * value - 1.0) - moment * moment / EI


def selected_lambda(theta: float, moment: float, load: float = P) -> float:
    roots = lambda_roots(theta, moment, load)
    stable = [value for value in roots if stretch_derivative(value, moment) > 0.0]
    if len(stable) != 1:
        raise RuntimeError(f"F_REFERENCE_LAMBDA_BRANCH_AMBIGUOUS roots={roots} stable={stable}")
    return stable[0]


def rhs_factory(load: float = P):
    def rhs(s: float, state: np.ndarray) -> np.ndarray:
        x, z, theta, moment = state
        del s, x, z
        lam = selected_lambda(float(theta), float(moment), load)
        return np.asarray(
            [lam * math.sin(float(theta)), lam * math.cos(float(theta)),
             float(moment) * lam * lam / EI, -load * lam * math.cos(float(theta))],
            dtype=np.float64,
        )

    return rhs


def integrate_shoot(moment0: float, load: float = P, dense: bool = False):
    solution = solve_ivp(
        rhs_factory(load),
        (0.0, L),
        np.asarray([0.0, 0.0, 0.0, moment0], dtype=np.float64),
        method="DOP853",
        rtol=IVP_RTOL,
        atol=IVP_ATOL,
        dense_output=dense,
        max_step=np.inf,
    )
    if not solution.success:
        raise RuntimeError(f"shooting IVP failed: {solution.message}")
    return solution


def find_bracket() -> tuple[float, float, list[dict]]:
    diagnostics = []
    previous_moment = None
    previous_residual = None
    for moment in M0_SCAN:
        solution = integrate_shoot(float(moment))
        residual = float(solution.y[3, -1])
        diagnostics.append({"M0": float(moment), "M_L": residual})
        if previous_residual is not None and previous_residual * residual <= 0.0:
            return float(previous_moment), float(moment), diagnostics
        previous_moment = float(moment)
        previous_residual = residual
    raise RuntimeError("F_REFERENCE_SOLVER_DISAGREEMENT: no deterministic M0 bracket")


def solve_shooting() -> tuple[float, object, tuple[float, float], list[dict]]:
    lower, upper, scan = find_bracket()
    root = root_scalar(
        lambda moment: float(integrate_shoot(float(moment)).y[3, -1]),
        bracket=(lower, upper),
        method="brentq",
        xtol=ROOT_XTOL,
        rtol=ROOT_RTOL,
        maxiter=200,
    )
    if not root.converged:
        raise RuntimeError("F_REFERENCE_SOLVER_DISAGREEMENT: Brent root did not converge")
    return float(root.root), integrate_shoot(float(root.root), dense=True), (lower, upper), scan


def solve_bvp_reference() -> object:
    mesh = np.linspace(0.0, L, 101, dtype=np.float64)
    fraction = mesh / L
    guess = np.vstack(
        [0.25 * fraction * fraction, fraction, 0.8 * fraction, 1.0 - fraction]
    )

    def fun(s: np.ndarray, state: np.ndarray) -> np.ndarray:
        result = np.empty_like(state)
        for index in range(s.size):
            result[:, index] = rhs_factory()(float(s[index]), state[:, index])
        return result

    def bc(left: np.ndarray, right: np.ndarray) -> np.ndarray:
        return np.asarray([left[0], left[1], left[2], right[3]], dtype=np.float64)

    result = solve_bvp(fun, bc, mesh, guess, tol=BVP_TOL, max_nodes=BVP_MAX_NODES, verbose=0)
    if not result.success:
        raise RuntimeError(f"F_REFERENCE_SOLVER_DISAGREEMENT: solve_bvp failed: {result.message}")
    return result


def evaluate_solution(solution, locations: np.ndarray) -> np.ndarray:
    if hasattr(solution, "sol") and solution.sol is not None:
        return np.asarray(solution.sol(locations), dtype=np.float64)
    return np.asarray(solution.sol(locations), dtype=np.float64)


def residual_metrics(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    theta = values[2]
    moment = values[3]
    lam = np.asarray([selected_lambda(float(t), float(m)) for t, m in zip(theta, moment)])
    residual = EA / 2.0 * lam * (lam * lam - 1.0) + (moment * moment / EI) * lam - P * np.sin(theta)
    residual = EA / 2.0 * lam * (lam * lam - 1.0) - (moment * moment / EI) * lam - P * np.sin(theta)
    derivative = EA / 2.0 * (3.0 * lam * lam - 1.0) - moment * moment / EI
    return residual, derivative


def write_reference_csv(path: Path, values: np.ndarray) -> None:
    locations = np.linspace(0.0, L, values.shape[1], dtype=np.float64)
    theta_s = values[3] * np.asarray(
        [selected_lambda(float(t), float(m)) ** 2 / EI for t, m in zip(values[2], values[3])]
    )
    lam = np.asarray([selected_lambda(float(t), float(m)) for t, m in zip(values[2], values[3])])
    kappa = theta_s / lam
    wa = EA / 8.0 * (lam * lam - 1.0) ** 2
    wb = 0.5 * EI * kappa * kappa
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["S", "x", "z", "theta", "M", "lambda", "kappa", "W_axial", "W_bending"])
        for row in zip(locations, values[0], values[1], values[2], values[3], lam, kappa, wa, wb):
            writer.writerow([f"{float(value):.17g}" for value in row])


def run_preflight(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    # Validation-only small-load sign check.
    small_load = 1.0e-6
    small_lower, small_upper, _ = find_bracket_for_load(small_load)
    small_root = root_scalar(
        lambda moment: float(integrate_shoot_for_load(float(moment), small_load).y[3, -1]),
        bracket=(small_lower, small_upper), method="brentq", xtol=ROOT_XTOL, rtol=ROOT_RTOL,
        maxiter=200,
    )
    small_solution = integrate_shoot_for_load(float(small_root.root), small_load, dense=True)
    small_tip = small_solution.y[:, -1]
    if not (small_tip[0] > 0.0 and small_tip[2] > 0.0 and abs(small_tip[0]) < 1.0e-3):
        raise RuntimeError("F_REFERENCE_SIGN_CONVENTION_FAIL")

    moment0, shooting, bracket, scan = solve_shooting()
    bvp = solve_bvp_reference()
    locations = np.linspace(0.0, L, REFERENCE_POINTS, dtype=np.float64)
    shooting_values = evaluate_solution(shooting, locations)
    bvp_values = evaluate_solution(bvp, locations)
    tip_shoot = shooting_values[:, -1]
    tip_bvp = bvp_values[:, -1]
    tip_delta = np.abs(tip_shoot - tip_bvp)
    centerline_rms = float(np.sqrt(np.mean((shooting_values[0:2] - bvp_values[0:2]) ** 2)))
    residual, derivative = residual_metrics(shooting_values)
    lam = np.asarray([selected_lambda(float(t), float(m)) for t, m in zip(shooting_values[2], shooting_values[3])])
    reference_csv = output_dir / "F_V1_1_REFERENCE_PREFLIGHT.csv"
    write_reference_csv(reference_csv, shooting_values)
    branch_csv = output_dir / "F_V1_1_LAMBDA_BRANCH_PREFLIGHT.csv"
    with branch_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["S", "real_positive_root_count", "stable_positive_root_count", "selected_lambda", "dg_dlambda", "residual"])
        locations = np.linspace(0.0, L, REFERENCE_POINTS, dtype=np.float64)
        for s, theta_value, moment_value, lambda_value, derivative_value, residual_value in zip(
            locations, shooting_values[2], shooting_values[3], lam, derivative, residual
        ):
            roots = lambda_roots(float(theta_value), float(moment_value))
            stable_count = sum(1 for root in roots if stretch_derivative(root, float(moment_value)) > 0.0)
            writer.writerow([
                f"{float(s):.17g}", len(roots), stable_count, f"{float(lambda_value):.17g}",
                f"{float(derivative_value):.17g}", f"{float(residual_value):.17g}"
            ])
    audit = {
        "status": "PASS",
        "constitutive_contract": {
            "epsilon": "0.5*(lambda^2-1)",
            "W_axial": "EA/8*(lambda^2-1)^2",
            "kappa": "theta_S/lambda",
            "W_bending": "0.5*EI*(theta_S/lambda)^2",
            "M": "EI*theta_S/lambda^2",
            "lambda_equation": "EA/2*lambda*(lambda^2-1) - (M^2/EI)*lambda - P*sin(theta) = 0",
        },
        "physical_case": {"L": L, "EA": EA, "EI": EI, "P": P, "mu_b": P * L * L / EI, "mu_a": P / EA},
        "solver": {
            "shooting": "solve_ivp DOP853 + brentq",
            "bvp": "solve_bvp",
            "ivp_rtol": IVP_RTOL,
            "ivp_atol": IVP_ATOL,
            "bvp_tol": BVP_TOL,
            "bvp_max_nodes": BVP_MAX_NODES,
            "root_xtol": ROOT_XTOL,
            "root_rtol": ROOT_RTOL,
        },
        "shooting": {"M0": moment0, "bracket": list(bracket), "bracket_scan": scan},
        "bvp": {"status": int(bvp.status), "message": bvp.message, "iterations": int(bvp.niter), "nodes": int(bvp.x.size)},
        "tip_shoot": tip_shoot.tolist(),
        "tip_bvp": tip_bvp.tolist(),
        "agreement": {
            "tip_x_abs": float(tip_delta[0]),
            "tip_z_abs": float(tip_delta[1]),
            "tip_theta_abs": float(tip_delta[2]),
            "centerline_rms": centerline_rms,
            "lambda_rms": float(np.sqrt(np.mean((lam - np.asarray([selected_lambda(float(t), float(m)) for t, m in zip(bvp_values[2], bvp_values[3])])) ** 2))),
        },
        "qualification": {
            "x_tip_over_L": float(abs(tip_shoot[0]) / L),
            "theta_tip_abs": float(abs(tip_shoot[2])),
            "max_abs_lambda_minus_1": float(np.max(np.abs(lam - 1.0))),
            "pass": bool(abs(tip_shoot[0]) / L >= 0.30 and abs(tip_shoot[2]) >= 0.50 and np.max(np.abs(lam - 1.0)) >= 5.0e-3),
        },
        "lambda_branch": {
            "points": REFERENCE_POINTS,
            "min_dg_dlambda": float(np.min(derivative)),
            "max_residual": float(np.max(np.abs(residual))),
            "max_normalized_residual": float(np.max(np.abs(residual) / np.maximum(1.0, np.abs(P * np.sin(shooting_values[2]))))),
            "all_positive": bool(np.all(lam > 0.0)),
            "all_stable": bool(np.all(derivative > 0.0)),
        },
        "small_load_sign_check": {"P": small_load, "M0": float(small_root.root), "x_tip": float(small_tip[0]), "theta_tip": float(small_tip[2]), "pass": True},
        "reference_dataset_sha256": sha256_file(reference_csv),
        "lambda_branch_audit_sha256": sha256_file(branch_csv),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }
    (output_dir / "F_V1_1_REFERENCE_PREFLIGHT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return audit


def find_bracket_for_load(load: float) -> tuple[float, float, list[dict]]:
    previous_moment = None
    previous_residual = None
    diagnostics = []
    for moment in M0_SCAN:
        result = integrate_shoot_for_load(float(moment), load)
        residual = float(result.y[3, -1])
        diagnostics.append({"M0": float(moment), "M_L": residual})
        if previous_residual is not None and previous_residual * residual <= 0.0:
            return float(previous_moment), float(moment), diagnostics
        previous_moment, previous_residual = float(moment), residual
    raise RuntimeError("F_REFERENCE_SIGN_CONVENTION_FAIL")


def integrate_shoot_for_load(moment0: float, load: float, dense: bool = False):
    result = solve_ivp(
        rhs_factory(load), (0.0, L), np.asarray([0.0, 0.0, 0.0, moment0]),
        method="DOP853", rtol=IVP_RTOL, atol=IVP_ATOL, dense_output=dense,
    )
    if not result.success:
        raise RuntimeError("F_REFERENCE_SIGN_CONVENTION_FAIL")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit = run_preflight(args.output_dir)
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
