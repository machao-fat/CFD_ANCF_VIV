"""Run the bounded Shiels S5-K9.88 no-fluid SDOF free-decay validation.

This runner intentionally calls the repository's existing ``SDOFRunner``.
It is not an alternate integrator: the analytical solution below is used only
for comparison.  The script refuses to reuse an output directory so one
invocation corresponds to one frozen, auditable bounded run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.coupling.sdof.sdof_runner import SDOFParameters, SDOFRunner  # noqa: E402


BENCHMARK_ID = "SHIELS_S5_K9P88_SDOF_FREE_DECAY_V1"
DT_S = 0.005
STEPS = 4470
T_END_S = 22.35
D_M = 1.0
U_MPS = 1.0
RHO_KGPM3 = 1000.0
NU_M2PS = 0.01
SPAN_M = 1.0
MASS_KG = 2500.0
STIFFNESS_NPM = 4940.0
DAMPING_NSPM = 0.0
Y0_M = 0.01
V0_MPS = 0.0
FORCE_N = 0.0

# These are frozen before the numerical loop.  Newmark average acceleration
# has O(dt^2) phase error for this oscillator; the bounds leave margin above
# that analytical discrete-dispersion estimate but remain far below 1%.
TOLERANCES = {
    "max_relative_y_error": 1.5e-4,
    "max_relative_v_error": 1.5e-4,
    "max_relative_a_error": 1.5e-4,
    "max_relative_frequency_error": 1.0e-5,
    "max_five_cycle_phase_drift_rad": 1.5e-4,
    "max_relative_energy_drift": 1.0e-10,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def exact(t: float, omega_n: float) -> tuple[float, float, float]:
    phase = omega_n * t
    y = Y0_M * math.cos(phase)
    v = -Y0_M * omega_n * math.sin(phase)
    a = -Y0_M * omega_n * omega_n * math.cos(phase)
    return y, v, a


def crossing_times(rows: list[dict[str, float]]) -> list[float]:
    result: list[float] = []
    for left, right in zip(rows, rows[1:]):
        yl, yr = left["y_m"], right["y_m"]
        if yl == 0.0:
            result.append(left["time_s"])
        elif yl * yr < 0.0:
            fraction = -yl / (yr - yl)
            result.append(left["time_s"] + fraction * (right["time_s"] - left["time_s"]))
    return result


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"refusing to reuse existing output directory: {output}")
    output.mkdir(parents=True)

    omega_n = math.sqrt(STIFFNESS_NPM / MASS_KG)
    fn_hz = omega_n / (2.0 * math.pi)
    period_s = 1.0 / fn_hz
    expected_a0 = -(STIFFNESS_NPM / MASS_KG) * Y0_M
    # SDOFRunner parameterization uses pi/4 displaced mass; convert only at
    # its public boundary while retaining the Shiels half-rho-D^2 contract.
    runner_mass_ratio = MASS_KG / (RHO_KGPM3 * math.pi * D_M * D_M / 4.0)
    reduced_velocity = U_MPS / (fn_hz * D_M)
    parameters = SDOFParameters(
        RHO_KGPM3, D_M, U_MPS, runner_mass_ratio, reduced_velocity, 0.0, DT_S
    )
    if abs(parameters.mass - MASS_KG) > 1.0e-10 or abs(parameters.stiffness - STIFFNESS_NPM) > 1.0e-9:
        raise RuntimeError("SDOFRunner conversion does not preserve the frozen M/K contract")
    if STEPS * DT_S != T_END_S:
        raise RuntimeError("frozen duration is not an integer number of time steps")

    script = Path(__file__).resolve()
    core = ROOT / "src" / "coupling" / "sdof" / "sdof_runner.py"
    cpp_kernel = ROOT / "src" / "coupling" / "cpp_worker_persistent_ipc_v1" / "ancf_kernel.cpp"
    contract = {
        "benchmark_id": BENCHMARK_ID,
        "source_contract": {
            "citation": "User-supplied Shiels et al. (2001), p.7 Table 2",
            "Re": 100,
            "m_star_shiels": 5.0,
            "k_star_shiels": 9.88,
            "b_star_shiels": 0.0,
            "definitions": {
                "m_star": "m_prime/(0.5*rho*D^2)",
                "k_star": "k_prime/(0.5*rho*U^2)",
            },
            "future_free_fsi_targets_not_used_here": {
                "A_over_D": 0.57,
                "fD_over_U": 0.198,
                "CL_amplitude": 1.35,
                "mean_CD": 2.23,
            },
        },
        "physical_scale": {
            "D_m": D_M, "U_mps": U_MPS, "rho_kgpm3": RHO_KGPM3,
            "nu_m2ps": NU_M2PS, "span_m": SPAN_M,
            "m_prime_kgpm": 2500.0, "k_prime_Npm2": 4940.0, "c_prime_Nspm2": 0.0,
            "M_kg": MASS_KG, "K_Npm": STIFFNESS_NPM, "C_Nspm": DAMPING_NSPM,
        },
        "equation": "M*y_ddot + C*y_dot + K*y = Fy; Fy=0; no added or displaced-fluid mass",
        "initial_state": {"y_m": Y0_M, "v_mps": V0_MPS, "a_mps2": expected_a0, "force_N": FORCE_N},
        "integrator": {
            "implementation": "src/coupling/sdof/sdof_runner.py:SDOFRunner",
            "method": "Newmark average acceleration", "beta": 0.25, "gamma": 0.5,
            "dt_s": DT_S, "steps": STEPS, "t_end_s": T_END_S,
        },
        "reference": {"omega_n_radps": omega_n, "fn_hz": fn_hz, "Tn_s": period_s},
        "tolerances": TOLERANCES,
        "scope": {
            "cfd_started": False, "precice_started": False, "free_fsi_started": False,
            "three_slice_started": False, "matlab_started": False, "wsl_started": False,
            "note": "Independent SDOF integrator validation only; not an ANCF or 50 m riser claim.",
        },
    }
    write_json(output / "contract.json", contract)

    runner = SDOFRunner(parameters)
    runner.initialize(y=Y0_M, v=V0_MPS)
    if abs(runner.state.a - expected_a0) > 1.0e-15:
        raise RuntimeError("initial acceleration differs from frozen force-free equilibrium")

    rows: list[dict[str, float]] = []
    for step in range(STEPS + 1):
        if step:
            t = step * DT_S
            runner.predict(step, t, FORCE_N)
            state, audit = runner.correct(step, t, FORCE_N)
        else:
            state = runner.state
            audit = {
                "mechanical_energy_J": 0.5 * MASS_KG * state.v**2 + 0.5 * STIFFNESS_NPM * state.y**2,
                "kinetic_energy_J": 0.5 * MASS_KG * state.v**2,
                "spring_energy_J": 0.5 * STIFFNESS_NPM * state.y**2,
            }
        y_ref, v_ref, a_ref = exact(state.time_s, omega_n)
        rows.append({
            "step": float(state.step), "time_s": state.time_s, "y_m": state.y,
            "v_mps": state.v, "a_mps2": state.a, "y_reference_m": y_ref,
            "v_reference_mps": v_ref, "a_reference_mps2": a_ref,
            "y_error_m": state.y - y_ref, "v_error_mps": state.v - v_ref,
            "a_error_mps2": state.a - a_ref,
            "mechanical_energy_J": audit["mechanical_energy_J"],
        })

    with (output / "trajectory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    max_y = max(abs(row["y_error_m"]) for row in rows)
    max_v = max(abs(row["v_error_mps"]) for row in rows)
    max_a = max(abs(row["a_error_mps2"]) for row in rows)
    crossings = crossing_times(rows)
    if len(crossings) < 8:
        raise RuntimeError("insufficient numerical zero crossings for the five-cycle frequency measurement")
    numerical_periods = [crossings[index + 2] - crossings[index] for index in range(len(crossings) - 2)]
    numerical_period_s = sum(numerical_periods) / len(numerical_periods)
    numerical_fn_hz = 1.0 / numerical_period_s
    terminal = rows[-1]
    phase_numerical = math.atan2(-terminal["v_mps"] / (Y0_M * omega_n), terminal["y_m"] / Y0_M)
    phase_reference = math.atan2(-terminal["v_reference_mps"] / (Y0_M * omega_n), terminal["y_reference_m"] / Y0_M)
    phase_drift = phase_reference - phase_numerical
    while phase_drift > math.pi:
        phase_drift -= 2.0 * math.pi
    while phase_drift < -math.pi:
        phase_drift += 2.0 * math.pi
    energy0 = rows[0]["mechanical_energy_J"]
    max_energy_drift = max(abs(row["mechanical_energy_J"] - energy0) for row in rows)
    metrics = {
        "max_abs_error": {"y_m": max_y, "v_mps": max_v, "a_mps2": max_a},
        "max_relative_error": {
            "y": max_y / Y0_M, "v": max_v / (Y0_M * omega_n), "a": max_a / (Y0_M * omega_n * omega_n),
        },
        "frequency": {
            "reference_hz": fn_hz, "zero_crossing_hz": numerical_fn_hz,
            "relative_error": abs(numerical_fn_hz - fn_hz) / fn_hz,
            "zero_crossing_count": len(crossings), "numerical_period_s": numerical_period_s,
        },
        "five_cycle_phase_drift_rad": phase_drift,
        "energy": {
            "initial_J": energy0, "final_J": terminal["mechanical_energy_J"],
            "max_abs_drift_J": max_energy_drift, "max_relative_drift": max_energy_drift / energy0,
        },
        "finite": all(math.isfinite(value) for row in rows for value in row.values()),
        "terminal_state": {key: terminal[key] for key in ("time_s", "y_m", "v_mps", "a_mps2", "mechanical_energy_J")},
    }
    pass_checks = {
        "finite": metrics["finite"],
        "relative_y": metrics["max_relative_error"]["y"] <= TOLERANCES["max_relative_y_error"],
        "relative_v": metrics["max_relative_error"]["v"] <= TOLERANCES["max_relative_v_error"],
        "relative_a": metrics["max_relative_error"]["a"] <= TOLERANCES["max_relative_a_error"],
        "frequency": metrics["frequency"]["relative_error"] <= TOLERANCES["max_relative_frequency_error"],
        "phase": abs(metrics["five_cycle_phase_drift_rad"]) <= TOLERANCES["max_five_cycle_phase_drift_rad"],
        "energy": metrics["energy"]["max_relative_drift"] <= TOLERANCES["max_relative_energy_drift"],
    }
    metrics["checks"] = pass_checks
    metrics["status"] = "PASS" if all(pass_checks.values()) else "FAIL"
    write_json(output / "metrics.json", metrics)

    times = [row["time_s"] for row in rows]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), constrained_layout=True)
    axes[0, 0].plot(times, [row["y_m"] for row in rows], label="SDOFRunner")
    axes[0, 0].plot(times, [row["y_reference_m"] for row in rows], "--", label="analytical")
    axes[0, 0].set(xlabel="t (s)", ylabel="y (m)", title="Displacement")
    axes[0, 0].legend()
    axes[0, 1].plot(times, [row["v_error_mps"] for row in rows], label="v error")
    axes[0, 1].plot(times, [row["a_error_mps2"] for row in rows], label="a error")
    axes[0, 1].set(xlabel="t (s)", ylabel="error", title="Velocity and acceleration error")
    axes[0, 1].legend()
    axes[1, 0].plot(times, [row["y_error_m"] for row in rows])
    axes[1, 0].set(xlabel="t (s)", ylabel="y - y_ref (m)", title="Displacement error")
    axes[1, 1].plot(times, [row["mechanical_energy_J"] for row in rows])
    axes[1, 1].set(xlabel="t (s)", ylabel="E (J)", title="Mechanical energy")
    fig.savefig(output / "free_decay_comparison.png", dpi=180)
    plt.close(fig)

    run_manifest = {
        "benchmark_id": BENCHMARK_ID, "pid": os.getpid(), "python": sys.version,
        "platform": platform.platform(), "git_head": git_head(),
        "runner_script": str(script), "runner_script_sha256": sha256(script),
        "sdof_core": str(core), "sdof_core_sha256": sha256(core),
        "cpp_ancf_kernel_audited_only": str(cpp_kernel), "cpp_ancf_kernel_sha256": sha256(cpp_kernel),
        "started_processes": {"python_sdof": 1, "cfd": 0, "precice": 0, "matlab": 0, "wsl": 0, "ancf_cpp_worker": 0},
        "return_code": 0 if metrics["status"] == "PASS" else 2,
    }
    write_json(output / "run_manifest.json", run_manifest)
    write_json(output / "run_status.json", {"status": metrics["status"], "steps_completed": STEPS, "t_end_s": T_END_S})
    print(json.dumps({"status": metrics["status"], "output": str(output), "metrics": metrics}, sort_keys=True))
    return 0 if metrics["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
