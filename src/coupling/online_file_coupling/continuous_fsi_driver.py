from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from scipy.io import loadmat
except ImportError:  # pragma: no cover - only used for checkpoint continuation
    loadmat = None

from ..file_exchange.csv_contract import MOTION_REQUIRED, atomic_write_csv
from ..structure_runners.persistent_matlab_runner import PersistentMatlabRunner
from .protocol import FileCouplingError, read_ready_snapshot, publish_ready


def _write_motion(path: Path, rows: list[dict[str, str]]) -> None:
    atomic_write_csv(path, MOTION_REQUIRED, rows)


def _load_matrix(rows: list[dict[str, str]]) -> list[list[float]]:
    return [[float(row["force_x_N"]), float(row["force_y_N"]), float(row["force_z_N"])] for row in rows]


def _project_structure_load(
    load: list[list[float]], *, branch: str, load_mode: str
) -> list[list[float]]:
    """Return the force sent to the structural comparator.

    ``transverse_only`` is an explicit cross-flow diagnostic: raw CFD force
    is retained in the audit, but only Fy reaches EB/ANCF.  The default
    ``full`` mode preserves the historical behaviour.
    """
    if load_mode not in {"full", "transverse_only"}:
        raise ValueError(f"unsupported load_mode {load_mode!r}")
    projected = [list(row) for row in load]
    for row in projected:
        if branch == "eb":
            row[2] = 0.0
        if load_mode == "transverse_only":
            row[0] = 0.0
            row[2] = 0.0
    return projected


def _stored_energy(energy: dict[str, Any]) -> float:
    if energy.get("stored_energy_J") not in (None, ""):
        return float(energy["stored_energy_J"])
    if energy.get("mechanical_energy_J") not in (None, ""):
        # Both structure solvers define mechanical_energy_J as kinetic plus
        # elastic/geometric energy plus the potential of time-independent
        # base loads.  The latter is essential for ANCF, where top tension is
        # applied as a conservative end load.
        return float(energy["mechanical_energy_J"])
    return (
        float(energy.get("kinetic_energy_J", 0.0))
        + float(energy.get("bending_energy_J", 0.0))
        + float(energy.get("axial_strain_energy_J", 0.0))
        + float(energy.get("pre_tension_geometric_energy_J", 0.0))
    )


def _wait_load(load_path: Path, marker_path: Path, *, step: int, time_s: float, s_ref: list[float], timeout_s: float) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout_s
    last_error = "marker not present"
    while time.monotonic() <= deadline:
        try:
            if marker_path.is_file():
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                marker_step = int(marker.get("step", -1))
                if marker_step == step:
                    return read_ready_snapshot(
                        load_path, marker_path, kind="load", expected_step=step,
                        expected_time_s=time_s, expected_s_ref_m=s_ref,
                    )
                if marker_step > step:
                    raise FileCouplingError(f"load marker jumped from requested step {step} to {marker_step}")
                last_error = f"waiting for load step {step}, current marker {marker_step}"
        except (OSError, ValueError, json.JSONDecodeError, FileCouplingError) as exc:
            last_error = str(exc)
        time.sleep(0.02)
    raise FileCouplingError(f"timeout waiting for load step {step}: {last_error}")


def _motion_row(rows: list[dict[str, str]]) -> dict[str, str]:
    if len(rows) != 1:
        raise FileCouplingError("continuous single-slice driver expects one motion row")
    return rows[0]


def _read_matlab_checkpoint_metadata(path: Path) -> tuple[int, float, list[list[float]]]:
    """Read only step/time/last load before loading the checkpoint in MATLAB."""
    if loadmat is None:
        raise FileCouplingError("scipy is required to inspect a MATLAB continuation checkpoint")
    data = loadmat(path, squeeze_me=True, struct_as_record=False)
    state = data.get("runner_state")
    if state is None:
        raise FileCouplingError(f"checkpoint has no runner_state: {path}")
    step = int(round(float(state.step)))
    time_s = float(state.t)
    last = [float(value) for value in list(state.last_slice_force_N)]
    if len(last) != 3:
        raise FileCouplingError(f"checkpoint last_slice_force_N is not 3D: {path}")
    if not all(map(lambda value: value == value and abs(value) != float("inf"), last)):
        raise FileCouplingError(f"checkpoint load is non-finite: {path}")
    return step, time_s, [last]


def _wait_motion_ack(path: Path, *, step: int, time_s: float, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() <= deadline:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if int(data["step"]) == step and abs(float(data["time_s"]) - time_s) <= 1.0e-10:
                    return
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
        time.sleep(0.02)
    raise FileCouplingError(f"timeout waiting for motion-consumed step {step}")


def run_case(
    *,
    branch: str,
    case_dir: Path,
    result_dir: Path,
    end_step: int,
    dt: float,
    config: dict[str, Any],
    load_mode: str = "full",
    timeout_s: float = 60.0,
    resume_checkpoint: Path | None = None,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    case_dir = case_dir.resolve()
    result_dir = result_dir.resolve()
    s_ref_values = list(config.get("s_ref_m", []))
    if len(s_ref_values) != 1:
        raise ValueError("continuous single-slice driver requires exactly one s_ref_m")
    config["s_ref_m"] = s_ref_values
    result_dir.mkdir(parents=True, exist_ok=True)
    coupling = case_dir / "coupling"
    motion_path = coupling / "motion.csv"
    motion_ready = coupling / "motion_ready"
    load_path = coupling / "slice_loads.csv"
    load_ready = coupling / "load_ready"
    (coupling / "consumed").mkdir(parents=True, exist_ok=True)
    runner_dir = result_dir / "matlab_runner"
    runner = PersistentMatlabRunner(branch=branch, config=config, request_dir=runner_dir, timeout_s=timeout_s)
    monitor_script = root / "tests" / "continuous_handshake" / "publish_load_from_forces.py"
    run_script = root / "tests" / "continuous_handshake" / "run_openfoam_case.ps1"
    py = sys.executable
    monitor = None
    solver = None
    monitor_log = None
    solver_log = None
    solver_err = None
    audit_rows: list[dict[str, Any]] = []
    previous_load = [[0.0, 0.0, 0.0]]
    previous_energy: dict[str, Any] = {}
    cumulative_w_cfd = 0.0
    cumulative_w_structure = 0.0
    cumulative_coupling_defect = 0.0
    cumulative_projection_defect = 0.0
    cumulative_temporal_defect = 0.0
    cumulative_damping = 0.0
    cumulative_structure_balance_residual = 0.0
    start_step = 0
    start_time_s = 0.0
    try:
        runner.start()
        if resume_checkpoint is not None:
            start_step, start_time_s, previous_load = _read_matlab_checkpoint_metadata(resume_checkpoint.resolve())
            if not abs(start_time_s - start_step * dt) <= 1.0e-10:
                raise FileCouplingError(
                    f"checkpoint step/time mismatch: step={start_step}, time={start_time_s}, dt={dt}"
                )
            runner.load_checkpoint(resume_checkpoint.resolve())
        force_time_name = "0" if resume_checkpoint is None else f"{start_time_s:.12g}"
        forces_path = case_dir / "postProcessing" / "cylinderForces" / force_time_name / "forces.dat"
        # PersistentMatlabRunner.get_energy() already unwraps the worker's
        # response.  A second .get("energy") used to discard the true initial
        # energy and created a spurious first-step/full-window residual.
        previous_energy = runner.get_energy()
        initial_rows = runner.get_motion()
        initial_motion = _motion_row(initial_rows)
        if int(float(initial_motion["step"])) != start_step or abs(float(initial_motion["time_s"]) - start_time_s) > 1.0e-10:
            raise FileCouplingError("loaded structure checkpoint motion does not match requested step/time")
        _write_motion(motion_path, initial_rows)
        publish_ready(motion_path, motion_ready, kind="motion", expected_s_ref_m=config["s_ref_m"])
        monitor_log = (result_dir / "load_monitor.log").open("w", encoding="utf-8")
        solver_log = (result_dir / "pimpleFoam.log").open("w", encoding="utf-8")
        solver_err = (result_dir / "pimpleFoam.err").open("w", encoding="utf-8")
        monitor = subprocess.Popen([
            py, str(monitor_script), "--forces", str(forces_path), "--coupling", str(coupling),
            "--start-step", str(start_step + 1), "--end-step", str(end_step), "--dt", str(dt), "--s-ref-m", str(float(config["s_ref_m"][0])),
            "--timeout-s", str(timeout_s),
        ], cwd=root, stdout=monitor_log, stderr=subprocess.STDOUT, text=True)
        wsl_case = "/mnt/" + str(case_dir.drive[0]).lower() + str(case_dir).replace("\\", "/")[2:]
        solver = subprocess.Popen([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(run_script),
            "-CasePath", wsl_case,
        ], cwd=root, stdout=solver_log, stderr=solver_err, text=True)
        _wait_motion_ack(coupling / "consumed" / f"motion_consumed_{start_step}.json", step=start_step, time_s=start_time_s, timeout_s=timeout_s)
        # The CFD initial field has no previously exchanged load file.  Use
        # the declared zero initial load for the first predictor and publish
        # step 1 immediately, before pimpleFoam can outrun the file handshake.
        next_step = start_step + 1
        next_time = next_step * dt
        _, predicted_rows = runner.predict(next_step, next_time, previous_load)
        _write_motion(motion_path, predicted_rows)
        publish_ready(motion_path, motion_ready, kind="motion", expected_s_ref_m=config["s_ref_m"])

        if end_step <= start_step:
            raise FileCouplingError(f"continuation end_step {end_step} is not beyond checkpoint step {start_step}")
        for step in range(start_step + 1, end_step + 1):
            time_s = step * dt
            wait_started = time.monotonic()
            load_rows = _wait_load(load_path, load_ready, step=step, time_s=time_s, s_ref=config["s_ref_m"], timeout_s=timeout_s)
            wait_s = time.monotonic() - wait_started
            current_load = _load_matrix(load_rows)
            raw_force = list(current_load[0])
            structure_load = _project_structure_load(
                current_load, branch=branch, load_mode=load_mode
            )
            correct_response, corrected_rows = runner.correct(step, time_s, structure_load)
            pred = _motion_row(predicted_rows)
            corr = _motion_row(corrected_rows)
            force = raw_force
            applied_force = structure_load[0]
            energy = correct_response.get("energy", {})
            pred_vx = float(pred["vx_mps"]); pred_vy = float(pred["vy_mps"])
            corr_vx = float(corr["vx_mps"]); corr_vy = float(corr["vy_mps"])
            cfd_power = force[0]*pred_vx + force[1]*pred_vy
            structure_power = applied_force[0]*corr_vx + applied_force[1]*corr_vy
            projection_defect_power = (
                (force[0]-applied_force[0])*pred_vx
                + (force[1]-applied_force[1])*pred_vy
            )
            temporal_defect_power = (
                applied_force[0]*(pred_vx-corr_vx)
                + applied_force[1]*(pred_vy-corr_vy)
            )
            cumulative_w_cfd += cfd_power*dt
            cumulative_w_structure += structure_power*dt
            cumulative_coupling_defect += (cfd_power-structure_power)*dt
            cumulative_projection_defect += projection_defect_power*dt
            cumulative_temporal_defect += temporal_defect_power*dt
            damping_power = float(energy.get("damping_power_W", 0.0))
            cumulative_damping += damping_power*dt
            stored_energy = _stored_energy(energy)
            previous_stored_energy = _stored_energy(previous_energy)
            delta_stored = stored_energy-previous_stored_energy
            balance_increment = structure_power*dt-delta_stored-damping_power*dt
            cumulative_structure_balance_residual += balance_increment
            previous_energy = energy
            def optional_force(name: str) -> float:
                try:
                    return float(load_rows[0].get(name, "nan"))
                except (TypeError, ValueError):
                    return float("nan")
            audit_rows.append({
                "step": step, "time_s": time_s, "coupling_iteration": 0,
                "predicted_x_m": float(pred["x_m"]), "predicted_y_m": float(pred["y_m"]),
                "corrected_x_m": float(corr["x_m"]), "corrected_y_m": float(corr["y_m"]),
                "predicted_vx_mps": float(pred["vx_mps"]), "predicted_vy_mps": float(pred["vy_mps"]),
                "corrected_vx_mps": float(corr["vx_mps"]), "corrected_vy_mps": float(corr["vy_mps"]),
                "predicted_ax_mps2": float(pred["ax_mps2"]), "predicted_ay_mps2": float(pred["ay_mps2"]),
                "corrected_ax_mps2": float(corr["ax_mps2"]), "corrected_ay_mps2": float(corr["ay_mps2"]),
                "force_x_N": force[0], "force_y_N": force[1], "force_z_N": force[2],
                "applied_force_x_N": structure_load[0][0],
                "applied_force_y_N": structure_load[0][1],
                "applied_force_z_N": structure_load[0][2],
                "pressure_force_x_N": optional_force("pressure_force_x_N"),
                "pressure_force_y_N": optional_force("pressure_force_y_N"),
                "viscous_force_x_N": optional_force("viscous_force_x_N"),
                "viscous_force_y_N": optional_force("viscous_force_y_N"),
                "predicted_displacement_residual_m": ((float(corr["x_m"])-float(pred["x_m"]))**2 + (float(corr["y_m"])-float(pred["y_m"]))**2) ** 0.5,
                "predicted_velocity_residual_mps": ((float(corr["vx_mps"])-float(pred["vx_mps"]))**2 + (float(corr["vy_mps"])-float(pred["vy_mps"]))**2) ** 0.5,
                "instantaneous_power_W": structure_power,
                "power_cfd_predicted_W": cfd_power,
                "power_structure_corrected_W": structure_power,
                "power_coupling_defect_W": cfd_power-structure_power,
                "power_load_projection_defect_W": projection_defect_power,
                "power_predictor_corrector_defect_W": temporal_defect_power,
                "fluid_work_cfd_J": cumulative_w_cfd,
                "structure_work_J": cumulative_w_structure,
                "coupling_defect_work_J": cumulative_coupling_defect,
                "load_projection_defect_work_J": cumulative_projection_defect,
                "predictor_corrector_defect_work_J": cumulative_temporal_defect,
                "damping_power_W": damping_power,
                "damping_dissipation_J": cumulative_damping,
                "stored_energy_previous_J": previous_stored_energy,
                "stored_energy_J": stored_energy,
                "delta_stored_energy_J": delta_stored,
                "structure_energy_balance_increment_J": balance_increment,
                "structure_energy_balance_residual_J": cumulative_structure_balance_residual,
                "mapped_generalized_force_norm_N": float(energy.get("mapped_generalized_force_norm_N", float("nan"))),
                "force_representation": load_rows[0].get("force_representation", ""),
                "unit_span_m": optional_force("unit_span_m"),
                "slice_length_m": optional_force("slice_length_m"),
                "wait_s": wait_s,
                "structure_iterations": correct_response.get("audit", {}).get("iterations", 0),
                "structure_residual": correct_response.get("audit", {}).get("residual", 0.0),
                "structure_converged": correct_response.get("audit", {}).get("converged", True),
                "mechanical_energy_J": energy.get("mechanical_energy_J", 0.0),
                "kinetic_energy_J": energy.get("kinetic_energy_J", 0.0),
                "bending_energy_J": energy.get("bending_energy_J", 0.0),
                "axial_strain_energy_J": energy.get("axial_strain_energy_J", 0.0),
                "pre_tension_geometric_energy_J": energy.get("pre_tension_geometric_energy_J", 0.0),
                "external_potential_energy_J": energy.get("external_potential_energy_J", 0.0),
                "internal_energy_J": energy.get("internal_energy_J", 0.0),
                "min_tension_N": energy.get("min_tension_N", float("nan")),
                "max_tension_N": energy.get("max_tension_N", float("nan")),
                "reference_tension_N": energy.get("reference_tension_N", float("nan")),
                "min_dynamic_tension_increment_N": energy.get("min_dynamic_tension_increment_N", float("nan")),
                "max_dynamic_tension_increment_N": energy.get("max_dynamic_tension_increment_N", float("nan")),
                "tension_location_index": energy.get("tension_location_index", float("nan")),
                "compression_risk": energy.get("compression_risk", False),
                "max_slope": energy.get("max_slope", float("nan")),
                "max_curvature_1pm": energy.get("max_curvature_1pm", float("nan")),
                "structure_initial_residual": correct_response.get("audit", {}).get("initial_residual", float("nan")),
                "structure_residual_scale": correct_response.get("audit", {}).get("residual_scale", float("nan")),
                "structure_initial_relative_residual": correct_response.get("audit", {}).get("initial_relative_residual", float("nan")),
                "structure_relative_residual": correct_response.get("audit", {}).get("relative_residual", float("nan")),
                "structure_tolerance_relative": correct_response.get("audit", {}).get("tolerance_relative", float("nan")),
                "status": "complete",
            })
            if step == start_step + (end_step - start_step) // 2:
                runner.save_checkpoint(result_dir / "midpoint_runner_checkpoint.mat")
            previous_load = structure_load
            if step < end_step:
                next_step = step + 1
                next_time = next_step * dt
                _, predicted_rows = runner.predict(next_step, next_time, previous_load)
                _write_motion(motion_path, predicted_rows)
                publish_ready(motion_path, motion_ready, kind="motion", expected_s_ref_m=config["s_ref_m"])

        fieldnames = list(audit_rows[0]) if audit_rows else ["status"]
        atomic_write_csv(result_dir / "coupling_audit.csv", fieldnames, audit_rows)
        return {
            "status": "complete", "branch": branch, "steps": len(audit_rows),
            "last_step": end_step, "load_mode": load_mode,
        }
    finally:
        if solver is not None and solver.poll() is None:
            solver.wait(timeout=timeout_s)
        if monitor is not None and monitor.poll() is None:
            monitor.terminate()
        for stream in (monitor_log, solver_log, solver_err):
            if stream is not None:
                stream.close()
        runner.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", choices=("eb", "ancf"), required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--end-step", type=int, default=100)
    parser.add_argument("--dt", type=float, default=0.0025)
    parser.add_argument("--top-tension", type=float, default=1.0e8)
    parser.add_argument("--youngs-modulus", type=float, default=2.07e11)
    parser.add_argument("--newton-tolerance", type=float, default=1.0e-8)
    parser.add_argument("--length", type=float, default=1.0)
    parser.add_argument("--diameter", type=float, default=1.0)
    parser.add_argument("--inner-diameter", type=float, default=0.9)
    parser.add_argument("--n-elem", type=int, default=2)
    parser.add_argument("--rayleigh-alpha", type=float, default=0.0)
    parser.add_argument("--rayleigh-beta", type=float, default=0.0)
    parser.add_argument("--resume-checkpoint", type=Path)
    parser.add_argument("--s-ref-m", type=float, required=True)
    parser.add_argument(
        "--load-mode", choices=("full", "transverse_only"), default="full",
        help="Project structural input to Fy only for a cross-flow diagnostic.",
    )
    args = parser.parse_args()
    config = {
        "L": args.length, "D": args.diameter, "dInner": args.inner_diameter, "nElem": args.n_elem, "nSlices": 1,
        "s_ref_m": [args.s_ref_m], "topTension_N": args.top_tension, "youngs_modulus_Pa": args.youngs_modulus, "dt": args.dt,
        "rayleigh_alpha": args.rayleigh_alpha, "rayleigh_beta": args.rayleigh_beta, "newton_tolerance": args.newton_tolerance,
    }
    print(json.dumps(run_case(
        branch=args.branch, case_dir=args.case, result_dir=args.results,
        end_step=args.end_step, dt=args.dt, config=config,
        load_mode=args.load_mode, resume_checkpoint=args.resume_checkpoint,
    )))


if __name__ == "__main__":
    main()
