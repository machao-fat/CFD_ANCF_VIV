"""File-handshake CFD runner for a one-transverse-DOF free cylinder.

This is intentionally separate from the beam runner: it is a screening and
benchmark layer for mass ratio, damping and reduced-velocity definitions.
The CFD force is never replayed between reduced velocities; every run starts
from a fresh case directory and consumes its own forces.dat stream.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .sdof_runner import SDOFParameters, SDOFRunner, SDOFState
from ..file_exchange.csv_contract import MOTION_REQUIRED, atomic_write_csv
from ..online_file_coupling.protocol import FileCouplingError, publish_ready, read_ready_snapshot


def _motion_row(step: int, time_s: float, y: float, vy: float, ay: float) -> dict[str, object]:
    return {
        "schema_version": "0.1.0", "step": step, "coupling_iteration": 0,
        "time_s": time_s, "slice_id": 0, "s_ref_m": 0.0,
        "x_m": 0.0, "y_m": y, "z_m": 0.0,
        "vx_mps": 0.0, "vy_mps": vy, "vz_mps": 0.0,
        "ax_mps2": 0.0, "ay_mps2": ay, "az_mps2": 0.0,
    }


def _write_motion(coupling: Path, row: dict[str, object]) -> int:
    path = coupling / "motion.csv"
    atomic_write_csv(path, MOTION_REQUIRED, [row])
    publish_ready(path, coupling / "motion_ready", kind="motion", expected_s_ref_m=[0.0])
    return (coupling / "motion_ready").stat().st_mtime_ns


def _wait_ack(coupling: Path, step: int, time_s: float, timeout_s: float, not_before_ns: int | None = None) -> None:
    path = coupling / "consumed" / f"motion_consumed_{step}.json"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() <= deadline:
        try:
            if path.is_file() and (not_before_ns is None or path.stat().st_mtime_ns >= not_before_ns):
                data = json.loads(path.read_text(encoding="utf-8"))
                if int(data["step"]) == step and abs(float(data["time_s"]) - time_s) <= 1.0e-10:
                    return
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
        time.sleep(0.02)
    raise FileCouplingError(f"timeout waiting for motion acknowledgement step {step}")


def _wait_load(coupling: Path, step: int, time_s: float, timeout_s: float) -> list[dict[str, str]]:
    load_path = coupling / "slice_loads.csv"
    marker_path = coupling / "load_ready"
    deadline = time.monotonic() + timeout_s
    last = "marker not present"
    while time.monotonic() <= deadline:
        try:
            if marker_path.is_file():
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                marker_step = int(marker.get("step", -1))
                if marker_step == step:
                    return read_ready_snapshot(
                        load_path, marker_path, kind="load", expected_step=step,
                        expected_time_s=time_s, expected_s_ref_m=[0.0],
                    )
                if marker_step > step:
                    raise FileCouplingError(f"load marker jumped to {marker_step}, requested {step}")
                last = f"waiting for load {step}, marker={marker_step}"
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, FileCouplingError) as exc:
            last = str(exc)
        time.sleep(0.02)
    raise FileCouplingError(f"timeout waiting for load step {step}: {last}")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _time_name(time_s: float) -> str:
    """Match OpenFOAM's general time formatting for the campaign time range."""
    return f"{time_s:.12g}"


def _latest_cfl(log_path: Path) -> float | None:
    if not log_path.is_file():
        return None
    pattern = re.compile(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)")
    latest = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            try:
                latest = float(match.group(1))
            except ValueError:
                pass
    return latest


def _load_checkpoint(path: Path, parameters: SDOFParameters) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "0.1.0":
        raise ValueError("unsupported SDOF checkpoint schema")
    saved = data.get("parameters", {})
    for key, current in parameters.as_dict().items():
        if key not in saved:
            raise ValueError(f"checkpoint parameter {key} is missing")
        saved_value = float(saved[key])
        if not math.isclose(saved_value, current, rel_tol=1.0e-12, abs_tol=1.0e-12):
            raise ValueError(f"checkpoint parameter mismatch for {key}: {saved_value} != {current}")
    return data


def _write_checkpoint(
    path: Path, *, parameters: SDOFParameters, runner: SDOFRunner,
    interface_state: dict[str, float | int],
    previous_force: float, cumulative_work: float, cumulative_cfd_work: float,
    cumulative_coupling_defect: float, cumulative_damping: float,
    cfd_time_directory: Path, audit_row_count: int,
) -> None:
    if not cfd_time_directory.is_dir():
        raise FileCouplingError(
            f"refusing unsynchronized checkpoint: CFD directory is missing: {cfd_time_directory}"
        )
    state = runner.state
    _atomic_write_json(path, {
        "schema_version": "0.1.0",
        "parameters": parameters.as_dict(),
        "state": vars(state),
        "interface_state_used_by_cfd": interface_state,
        "previous_force_y_N": previous_force,
        "cumulative": {
            "fluid_work_structure_J": cumulative_work,
            "fluid_work_cfd_predicted_J": cumulative_cfd_work,
            "coupling_defect_work_J": cumulative_coupling_defect,
            "damping_dissipation_J": cumulative_damping,
        },
        "cfd": {
            "time_s": state.time_s,
            "time_directory": str(cfd_time_directory.resolve()),
        },
        "audit_row_count_this_segment": audit_row_count,
    })


def _wait_for_cfd_time_directory(case_dir: Path, time_s: float, timeout_s: float = 15.0) -> Path:
    path = case_dir / _time_name(time_s)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() <= deadline:
        if path.is_dir() and (path / "U").is_file() and (path / "p").is_file():
            return path
        time.sleep(0.05)
    raise FileCouplingError(f"CFD fields were not written at synchronized time {time_s}: {path}")


def run_case(
    *, case_dir: Path, result_dir: Path, parameters: SDOFParameters,
    end_step: int, startup_steps: int, initial_y_m: float = 1.0e-3,
    timeout_s: float = 120.0, resume_checkpoint: Path | None = None,
    checkpoint_interval: int = 500, forces_path: Path | None = None,
    max_displacement_factor: float = 1.5, max_cfl: float = 0.5,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    case_dir = case_dir.resolve()
    coupling = case_dir / "coupling"
    result_dir = result_dir.resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    coupling.mkdir(parents=True, exist_ok=True)
    (coupling / "consumed").mkdir(parents=True, exist_ok=True)
    monitor_script = root / "tests" / "continuous_handshake" / "publish_load_from_forces.py"
    run_script = root / "tests" / "continuous_handshake" / "run_openfoam_case.ps1"
    monitor = solver = None
    audit: list[dict[str, Any]] = []
    runner = SDOFRunner(parameters)
    previous_force = 0.0
    cumulative_work = 0.0
    cumulative_cfd_work = 0.0
    cumulative_coupling_defect = 0.0
    cumulative_damping = 0.0
    log_handle = None
    err_handle = None
    try:
        start_step = 0
        resume_source = None
        resume_interface_state: dict[str, float | int] | None = None
        if resume_checkpoint is None:
            runner.initialize(y=initial_y_m)
        else:
            resume_source = resume_checkpoint.resolve()
            checkpoint = _load_checkpoint(resume_source, parameters)
            state_data = checkpoint.get("state", {})
            runner.restore(SDOFState(
                y=float(state_data["y"]), v=float(state_data["v"]),
                a=float(state_data["a"]), step=int(state_data["step"]),
                time_s=float(state_data["time_s"]),
            ))
            start_step = runner.state.step
            if start_step < startup_steps:
                raise ValueError("resume checkpoint precedes the fixed-flow startup boundary")
            if end_step <= start_step:
                raise ValueError("end_step must be greater than the checkpoint step")
            previous_force = float(checkpoint["previous_force_y_N"])
            resume_interface_state = checkpoint.get("interface_state_used_by_cfd")
            if resume_interface_state is None:
                raise ValueError("checkpoint has no CFD interface state")
            if int(resume_interface_state["step"]) != start_step:
                raise ValueError("checkpoint interface step does not match structure state")
            if not math.isclose(
                float(resume_interface_state["time_s"]), runner.state.time_s,
                rel_tol=0.0, abs_tol=1.0e-10,
            ):
                raise ValueError("checkpoint interface time does not match structure state")
            cumulative = checkpoint.get("cumulative", {})
            cumulative_work = float(cumulative.get("fluid_work_structure_J", 0.0))
            cumulative_cfd_work = float(cumulative.get("fluid_work_cfd_predicted_J", 0.0))
            cumulative_coupling_defect = float(cumulative.get("coupling_defect_work_J", 0.0))
            cumulative_damping = float(cumulative.get("damping_dissipation_J", 0.0))
            expected_cfd_time = float(checkpoint.get("cfd", {}).get("time_s", math.nan))
            if not math.isclose(expected_cfd_time, runner.state.time_s, rel_tol=0.0, abs_tol=1.0e-10):
                raise ValueError("checkpoint CFD time and SDOF state time do not match")
            case_time_dir = case_dir / _time_name(runner.state.time_s)
            if not case_time_dir.is_dir():
                raise ValueError(f"case has no CFD restart directory {case_time_dir}")
        parameter_record = parameters.as_dict()
        parameter_record.update({
            "initial_y_m": initial_y_m, "startup_steps": startup_steps,
            "start_step": start_step, "start_time_s": runner.state.time_s,
            "resume_checkpoint": str(resume_source) if resume_source else None,
            "checkpoint_interval": checkpoint_interval,
            "safety_limits": {
                "max_abs_displacement_m": max_displacement_factor * parameters.diameter,
                "max_cfl": max_cfl,
            },
        })
        (result_dir / "parameters.json").write_text(json.dumps(parameter_record, indent=2) + "\n", encoding="utf-8")
        if forces_path is None:
            force_start_name = "0" if start_step == 0 else _time_name(runner.state.time_s)
            forces = case_dir / "postProcessing" / "cylinderForces" / force_start_name / "forces.dat"
        else:
            forces = forces_path.resolve()
        if resume_interface_state is not None:
            seed_y = float(resume_interface_state["y"])
            seed_v = float(resume_interface_state["v"])
            seed_a = float(resume_interface_state["a"])
        else:
            seed_y = runner.state.y if startup_steps == 0 else 0.0
            seed_v = 0.0
            seed_a = 0.0
        seed_ready_mtime = _write_motion(coupling, _motion_row(start_step, runner.state.time_s, seed_y, seed_v, seed_a))
        log_handle = (result_dir / "pimpleFoam.log").open("w", encoding="utf-8")
        err_handle = (result_dir / "pimpleFoam.err").open("w", encoding="utf-8")
        monitor = subprocess.Popen([
            sys.executable, str(monitor_script), "--forces", str(forces), "--coupling", str(coupling),
            "--start-step", str(start_step + 1), "--end-step", str(end_step),
            "--dt", str(parameters.dt), "--s-ref-m", "0.0", "--timeout-s", str(timeout_s),
        ], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True)
        wsl_case = "/mnt/" + str(case_dir.drive[0]).lower() + str(case_dir).replace("\\", "/")[2:]
        solver = subprocess.Popen([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(run_script),
            "-CasePath", wsl_case,
        ], cwd=root, stdout=log_handle, stderr=err_handle, text=True)
        # A resumed case already contains a historical acknowledgement for the
        # checkpoint step.  Require the acknowledgement written by this solver
        # startup, otherwise the next motion can race the initial mesh read.
        _wait_ack(coupling, start_step, runner.state.time_s, timeout_s, not_before_ns=seed_ready_mtime)

        # Publish the first motion.  During the fixed-flow startup the motion
        # remains zero and the force is only recorded for the startup audit.
        predicted_current = None
        if start_step > 0:
            predicted_current = runner.predict(start_step + 1, (start_step + 1) * parameters.dt, previous_force)
            _write_motion(coupling, _motion_row(
                start_step + 1, (start_step + 1) * parameters.dt,
                predicted_current.y, predicted_current.v, predicted_current.a,
            ))
        elif startup_steps >= 1:
            _write_motion(coupling, _motion_row(1, parameters.dt, 0.0, 0.0, 0.0))
        else:
            predicted_current = runner.predict(1, parameters.dt, previous_force)
            _write_motion(coupling, _motion_row(1, parameters.dt, predicted_current.y, predicted_current.v, predicted_current.a))

        for step in range(start_step + 1, end_step + 1):
            time_s = step * parameters.dt
            rows = _wait_load(coupling, step, time_s, timeout_s)
            row = rows[0]
            fy = float(row["force_y_N"])
            pressure_fy = float(row.get("pressure_force_y_N", fy))
            viscous_fy = float(row.get("viscous_force_y_N", 0.0))
            if step <= startup_steps:
                y = v = a = 0.0
                dy = dv = 0.0
                predicted_y = predicted_v = predicted_a = 0.0
                energy = {"mechanical_energy_J": 0.0, "damping_power_W": 0.0}
            else:
                predicted_y, predicted_v, predicted_a = (
                    predicted_current.y, predicted_current.v, predicted_current.a
                )
                corrected, energy = runner.correct(step, time_s, fy)
                y, v, a = corrected.y, corrected.v, corrected.a
                # The current predictor used the previous-step force.  Compare
                # it with the correction driven by the newly received force.
                dy = corrected.y - predicted_current.y if predicted_current is not None else 0.0
                dv = corrected.v - predicted_current.v if predicted_current is not None else 0.0
                predicted_current = None
            power = fy * v
            cfd_power = fy * predicted_v
            coupling_defect_power = cfd_power-power
            cumulative_cfd_work += cfd_power*parameters.dt
            cumulative_coupling_defect += coupling_defect_power*parameters.dt
            cumulative_work += power * parameters.dt
            cumulative_damping += float(energy["damping_power_W"]) * parameters.dt
            audit.append({
                "step": step, "time_s": time_s, "startup_fixed": int(step <= startup_steps),
                "pressure_force_y_N": pressure_fy, "viscous_force_y_N": viscous_fy, "force_y_N": fy,
                "Cd": float(row.get("force_x_N", 0.0))/(0.5*parameters.rho*parameters.flow_speed**2*parameters.diameter),
                "Cl": fy/(0.5*parameters.rho*parameters.flow_speed**2*parameters.diameter),
                "predicted_y_m": predicted_y, "predicted_vy_mps": predicted_v,
                "predicted_ay_mps2": predicted_a,
                "y_m": y, "vy_mps": v, "ay_mps2": a,
                "predictor_displacement_residual_m": dy,
                "predictor_velocity_residual_mps": dv,
                "instantaneous_power_W": power,
                "power_cfd_predicted_W": cfd_power,
                "power_coupling_defect_W": coupling_defect_power,
                "fluid_work_J": cumulative_work,
                "fluid_work_cfd_predicted_J": cumulative_cfd_work,
                "coupling_defect_work_J": cumulative_coupling_defect,
                "damping_dissipation_J": cumulative_damping,
                "kinetic_energy_J": energy.get("kinetic_energy_J", 0.0),
                "spring_energy_J": energy.get("spring_energy_J", 0.0),
                "mechanical_energy_J": energy.get("mechanical_energy_J", 0.0),
            })
            if abs(y) > max_displacement_factor * parameters.diameter:
                raise FileCouplingError(
                    f"safety stop: |y|={abs(y):.6g} m exceeds "
                    f"{max_displacement_factor:g}D"
                )
            cfl = _latest_cfl(result_dir / "pimpleFoam.log")
            if cfl is not None and (not math.isfinite(cfl) or cfl > max_cfl):
                raise FileCouplingError(
                    f"safety stop: CFD max CFL={cfl} exceeds limit {max_cfl:g}"
                )
            if step % 100 == 0:
                atomic_write_csv(result_dir / "sdof_audit.csv", list(audit[0]), audit)
            previous_force = fy
            if step < startup_steps:
                _write_motion(coupling, _motion_row(step + 1, (step + 1) * parameters.dt, 0.0, 0.0, 0.0))
            elif step == startup_steps and step < end_step:
                runner.initialize(y=initial_y_m, v=0.0, step=step, time_s=time_s)
                predicted_current = runner.predict(step + 1, (step + 1) * parameters.dt, previous_force)
                _write_motion(coupling, _motion_row(step + 1, (step + 1) * parameters.dt, predicted_current.y, predicted_current.v, predicted_current.a))
            elif step > startup_steps and step < end_step:
                predicted_current = runner.predict(step + 1, (step + 1) * parameters.dt, previous_force)
                _write_motion(coupling, _motion_row(step + 1, (step + 1) * parameters.dt, predicted_current.y, predicted_current.v, predicted_current.a))

            if checkpoint_interval > 0 and step > startup_steps and step % checkpoint_interval == 0:
                cfd_time_directory = _wait_for_cfd_time_directory(case_dir, time_s)
                _write_checkpoint(
                    result_dir / "sdof_checkpoint.json", parameters=parameters, runner=runner,
                    interface_state={
                        "y": predicted_y, "v": predicted_v, "a": predicted_a,
                        "step": step, "time_s": time_s,
                    },
                    previous_force=previous_force, cumulative_work=cumulative_work,
                    cumulative_cfd_work=cumulative_cfd_work,
                    cumulative_coupling_defect=cumulative_coupling_defect,
                    cumulative_damping=cumulative_damping,
                    cfd_time_directory=cfd_time_directory, audit_row_count=len(audit),
                )

        if audit:
            atomic_write_csv(result_dir / "sdof_audit.csv", list(audit[0]), audit)
        return {
            "status": "complete", "steps_this_segment": len(audit),
            "first_step": start_step + 1, "last_step": end_step,
            "last_time_s": end_step * parameters.dt, "Ur": parameters.reduced_velocity,
        }
    finally:
        if audit:
            atomic_write_csv(result_dir / "sdof_audit.csv", list(audit[0]), audit)
        if solver is not None and solver.poll() is None:
            try:
                solver.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                solver.kill()
        if monitor is not None and monitor.poll() is None:
            monitor.terminate()
        if log_handle is not None:
            log_handle.close()
        if err_handle is not None:
            err_handle.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--Ur", type=float, required=True)
    parser.add_argument("--end-step", type=int, default=8000)
    parser.add_argument("--startup-steps", type=int, default=800)
    parser.add_argument("--initial-y", type=float, default=1.0e-3)
    parser.add_argument("--dt", type=float, default=0.0025)
    parser.add_argument("--mass-ratio", type=float, default=10.0)
    parser.add_argument("--damping-ratio", type=float, default=0.01)
    parser.add_argument("--resume-checkpoint", type=Path)
    parser.add_argument("--checkpoint-interval", type=int, default=500)
    parser.add_argument("--forces-path", type=Path)
    parser.add_argument("--max-displacement-factor", type=float, default=1.5)
    parser.add_argument("--max-cfl", type=float, default=0.5)
    args = parser.parse_args()
    p = SDOFParameters(1000.0, 1.0, 1.0, args.mass_ratio, args.Ur, args.damping_ratio, args.dt)
    try:
        print(json.dumps(run_case(
            case_dir=args.case, result_dir=args.results, parameters=p,
            end_step=args.end_step, startup_steps=args.startup_steps,
            initial_y_m=args.initial_y, resume_checkpoint=args.resume_checkpoint,
            checkpoint_interval=args.checkpoint_interval, forces_path=args.forces_path,
            max_displacement_factor=args.max_displacement_factor, max_cfl=args.max_cfl,
        )))
    except (FileCouplingError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
