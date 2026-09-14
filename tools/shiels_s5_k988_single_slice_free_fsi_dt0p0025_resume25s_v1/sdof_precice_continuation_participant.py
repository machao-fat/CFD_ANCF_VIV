"""Checkpoint-aware continuation wrapper around the existing SDOFRunner.

This is test-only coupling glue.  It does not replace the project's SDOF
integrator, ANCF core, OpenFOAM adapter, or force mapping implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.coupling.sdof.sdof_runner import SDOFParameters, SDOFRunner, SDOFState  # noqa: E402


MASS_KG = 2500.0
STIFFNESS_NPM = 4940.0
DAMPING_NSPM = 0.0
RHO_KGPM3 = 1000.0
DIAMETER_M = 1.0
FLOW_SPEED_MPS = 1.0


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def make_runner(*, dt_s: float, initial_y_m: float, initial_v_mps: float, initial_force_y_N: float) -> SDOFRunner:
    """Build the existing runner and restore its force-consistent initial state.

    ``SDOFRunner.initialize`` correctly assumes zero force by design.  The
    free-FSI initial state is instead restored with the measured CFD force so
    acceleration remains synchronized with the physical start time.
    """
    omega = math.sqrt(STIFFNESS_NPM / MASS_KG)
    fn = omega / (2.0 * math.pi)
    runner_mass_ratio = MASS_KG / (RHO_KGPM3 * math.pi * DIAMETER_M**2 / 4.0)
    reduced_velocity = FLOW_SPEED_MPS / (fn * DIAMETER_M)
    parameters = SDOFParameters(
        RHO_KGPM3, DIAMETER_M, FLOW_SPEED_MPS, runner_mass_ratio, reduced_velocity, 0.0, dt_s
    )
    if abs(parameters.mass - MASS_KG) > 1.0e-10 or abs(parameters.stiffness - STIFFNESS_NPM) > 1.0e-9:
        raise RuntimeError("SDOFRunner public-parameter conversion changed the Shiels M/K contract")
    if DAMPING_NSPM != 0.0 or parameters.damping != 0.0:
        raise RuntimeError("this benchmark requires zero structural damping")
    if not all(math.isfinite(value) for value in (initial_y_m, initial_v_mps, initial_force_y_N)):
        raise ValueError("initial state/force is non-finite")
    runner = SDOFRunner(parameters)
    runner.initialize(y=initial_y_m, v=initial_v_mps)
    a0 = (initial_force_y_N - STIFFNESS_NPM * initial_y_m - DAMPING_NSPM * initial_v_mps) / MASS_KG
    # Preserve force-consistent a0 in an explicit state restoration.  This is
    # deliberately not a direct mutable assignment and is the same public
    # checkpoint API used for coupling rollbacks below.
    runner.restore(SDOFState(y=initial_y_m, v=initial_v_mps, a=a0, step=0, time_s=0.0))
    return runner


def state_payload(state: SDOFState) -> dict[str, float | int]:
    return {"y_m": state.y, "v_mps": state.v, "a_mps2": state.a, "step": state.step, "local_time_s": state.time_s}


def clone_state(state: SDOFState) -> SDOFState:
    return SDOFState(**vars(state))


@dataclass
class PhysicalCheckpoint:
    """Physical state only; no preCICE transport identity is restored."""

    state: SDOFState
    previous_force_y_N: float
    cumulative_fluid_work_J: float
    cumulative_energy_defect_J: float
    accepted_windows: int
    checkpoint_id: str

    @classmethod
    def capture(cls, runner: SDOFRunner, previous_force_y_N: float, cumulative_fluid_work_J: float,
                cumulative_energy_defect_J: float, accepted_windows: int, checkpoint_id: str) -> "PhysicalCheckpoint":
        return cls(clone_state(runner.state), previous_force_y_N, cumulative_fluid_work_J,
                   cumulative_energy_defect_J, accepted_windows, checkpoint_id)

    def payload(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "state": state_payload(self.state),
            "previous_force_y_N": self.previous_force_y_N,
            "cumulative_fluid_work_J": self.cumulative_fluid_work_J,
            "cumulative_energy_defect_J": self.cumulative_energy_defect_J,
            "accepted_windows": self.accepted_windows,
        }

    def restore(self, runner: SDOFRunner) -> None:
        runner.restore(clone_state(self.state))


def force_sum_y(value: Any, count: int) -> tuple[float, str]:
    rows = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(rows, list) or len(rows) != count:
        raise RuntimeError(f"preCICE Force vertex count mismatch: expected {count}")
    normalized: list[list[float]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise RuntimeError("preCICE Force data must be a 2D vector at every Structure-Mesh vertex")
        converted = [float(row[0]), float(row[1])]
        if not all(math.isfinite(item) for item in converted):
            raise RuntimeError("preCICE Force contains NaN/Inf")
        normalized.append(converted)
    return sum(row[1] for row in normalized), canonical(normalized)


def displacement_payload(y_m: float, count: int) -> tuple[list[list[float]], str]:
    if not math.isfinite(y_m) or count <= 0:
        raise RuntimeError("invalid SDOF displacement payload")
    values = [[0.0, y_m] for _ in range(count)]
    return values, canonical(values)


def energy(state: SDOFState) -> float:
    return 0.5 * MASS_KG * state.v**2 + 0.5 * STIFFNESS_NPM * state.y**2


def enforce_emergency_protection(*, state: SDOFState, limits: dict[str, float],
                                 runtime: Path, phase: str, physical_time_s: float,
                                 window_index: int, iteration_index: int) -> None:
    """Stop an unsafe trial before commit; this is runtime protection only."""
    checks = {
        "abs_y_m": (abs(state.y), limits["max_abs_y_m"]),
        "abs_v_mps": (abs(state.v), limits["max_abs_v_mps"]),
    }
    failed = {name: {"value": value, "limit": limit}
              for name, (value, limit) in checks.items() if value > limit}
    if not failed:
        return
    append_jsonl(runtime / "events.jsonl", {
        "event": "emergency_stop", "phase": phase,
        "physical_time_s": physical_time_s, "window_index": window_index,
        "iteration_index": iteration_index, "state": state_payload(state),
        "limits": limits, "violations": failed,
        "policy": "hard runtime protection only; not a Shiels validation criterion",
    })
    raise RuntimeError(f"emergency protection triggered during {phase}: {failed}")


def self_test() -> dict[str, Any]:
    """No-preCICE unit checks for the new wrapper's state and unit contract."""
    dt = 0.005
    omega = math.sqrt(STIFFNESS_NPM / MASS_KG)
    rows: dict[str, Any] = {}

    zero = make_runner(dt_s=dt, initial_y_m=0.01, initial_v_mps=0.0, initial_force_y_N=0.0)
    for step in range(1, 101):
        zero.predict(step, step * dt, 0.0)
        zero_state, _ = zero.correct(step, step * dt, 0.0)
    y_ref = 0.01 * math.cos(omega * 100 * dt)
    rows["zero_force"] = {"abs_y_error_m": abs(zero_state.y - y_ref), "pass": abs(zero_state.y - y_ref) < 1.0e-7}

    constant_force = 20.0
    constant = make_runner(dt_s=dt, initial_y_m=0.0, initial_v_mps=0.0, initial_force_y_N=constant_force)
    for step in range(1, 101):
        constant.predict(step, step * dt, constant_force)
        constant_state, _ = constant.correct(step, step * dt, constant_force)
    t = 100 * dt
    y_ref = constant_force / STIFFNESS_NPM * (1.0 - math.cos(omega * t))
    rows["constant_force"] = {"abs_y_error_m": abs(constant_state.y - y_ref), "pass": abs(constant_state.y - y_ref) < 1.0e-7}

    initial_force = -7.0
    first = make_runner(dt_s=dt, initial_y_m=0.0, initial_v_mps=0.0, initial_force_y_N=initial_force)
    checkpoint = PhysicalCheckpoint.capture(first, initial_force, 0.0, 0.0, 0, "unit_window_000001")
    first.predict(1, dt, initial_force)
    first.correct(1, dt, 13.0)  # rejected trial A
    checkpoint.restore(first)
    first.predict(1, dt, initial_force)
    restored_b, _ = first.correct(1, dt, -5.0)
    direct = make_runner(dt_s=dt, initial_y_m=0.0, initial_v_mps=0.0, initial_force_y_N=initial_force)
    direct.predict(1, dt, initial_force)
    direct_b, _ = direct.correct(1, dt, -5.0)
    delta = max(abs(restored_b.y - direct_b.y), abs(restored_b.v - direct_b.v), abs(restored_b.a - direct_b.a))
    rows["trial_restore_accept"] = {"max_state_delta": delta, "checkpoint_sha256": canonical(checkpoint.payload()), "pass": delta <= 1.0e-15}

    continued = make_runner(dt_s=dt, initial_y_m=-2.4e-6, initial_v_mps=-7.0e-5, initial_force_y_N=-2.6)
    continued.restore(SDOFState(y=-2.4e-6, v=-7.0e-5, a=-1.0e-3, step=10, time_s=0.05))
    continued_checkpoint = PhysicalCheckpoint.capture(continued, -2.6, 6.0e-6, 0.0, 0, "unit_continuation")
    continued.predict(11, 0.055, -2.6)
    first_b, _ = continued.correct(11, 0.055, -1.3)
    continued_checkpoint.restore(continued)
    continued.predict(11, 0.055, -2.6)
    second_b, _ = continued.correct(11, 0.055, -1.3)
    continuation_delta = max(abs(first_b.y - second_b.y), abs(first_b.v - second_b.v), abs(first_b.a - second_b.a))
    rows["accepted_restart_trial_restore"] = {
        "initial_step": 10, "next_step": second_b.step, "next_local_time_s": second_b.time_s,
        "max_state_delta": continuation_delta,
        "pass": second_b.step == 11 and abs(second_b.time_s - 0.055) <= 1.0e-15 and continuation_delta <= 1.0e-15,
    }

    values, payload_sha = displacement_payload(0.002, 40)
    fy, force_sha = force_sum_y([[1.0, -0.5] for _ in range(40)], 40)
    rows["time_layer_and_units"] = {
        "initial_physical_time_s": 0.105, "first_output_time_s": 0.11,
        "displacement_shape": [len(values), len(values[0])], "displacement_payload_sha256": payload_sha,
        "force_sum_y_N": fy, "force_payload_sha256": force_sha,
        "pass": len(values) == 40 and fy == -20.0,
    }
    status = "PASS" if all(bool(value["pass"]) for value in rows.values()) else "FAIL"
    return {"schema_version": "shiels-sdof-precice-wrapper-unit-v1", "status": status, "checks": rows,
            "scope": "No CFD/preCICE; tests only the new wrapper around existing SDOFRunner."}


def run_participant(args: argparse.Namespace) -> int:
    import precice

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    dt = float(contract["coupling"]["dt_s"])
    steps = int(contract["coupling"]["accepted_window_limit"])
    start = float(contract["coupling"]["start_of_time_s"])
    restart = contract.get("restart")
    if restart is None:
        initial_force = float(contract["initial_state"]["Fy0_total_N"])
        initial_interface_y = 0.0
        restored_state: SDOFState | None = None
        restart_work = 0.0
        restart_defect = 0.0
        prior_accepted_windows = 0
    else:
        initial_force = float(restart["previous_accepted_force_y_N"])
        initial_interface_y = float(restart["initial_interface_y_m"])
        payload = restart["sdof_state"]
        restored_state = SDOFState(
            y=float(payload["y_m"]), v=float(payload["v_mps"]),
            a=float(payload["a_mps2"]), step=int(payload["step"]),
            time_s=float(payload["local_time_s"]),
        )
        if not all(math.isfinite(value) for value in (initial_force, initial_interface_y)):
            raise RuntimeError("restart force/interface displacement is non-finite")
        restart_work = float(restart["cumulative_fluid_work_J"])
        restart_defect = float(restart["cumulative_energy_balance_defect_J"])
        prior_accepted_windows = int(restart["prior_accepted_windows"])
        if not all(math.isfinite(value) for value in (restart_work, restart_defect)) or prior_accepted_windows < 0:
            raise RuntimeError("restart energy/accounting state is invalid")
    protection_raw = contract.get("emergency_protection")
    if not isinstance(protection_raw, dict):
        raise RuntimeError("missing emergency_protection contract")
    protection = {
        "max_abs_y_m": float(protection_raw["max_abs_y_m"]),
        "max_abs_v_mps": float(protection_raw["max_abs_v_mps"]),
    }
    if not all(math.isfinite(value) and value > 0.0 for value in protection.values()):
        raise RuntimeError("emergency protection limits must be finite and positive")
    vertex_count = int(args.vertex_count)
    if args.runtime.exists() and (args.runtime / "structure_summary.json").exists():
        raise RuntimeError("structure runtime already has execution evidence; rerun forbidden")
    args.runtime.mkdir(parents=True, exist_ok=False)
    runner = make_runner(
        dt_s=dt,
        initial_y_m=0.0 if restored_state is None else restored_state.y,
        initial_v_mps=0.0 if restored_state is None else restored_state.v,
        initial_force_y_N=initial_force,
    )
    if restored_state is not None:
        # Restore the accepted Newmark state exactly, including acceleration,
        # global SDOF step and local runner time.  Do not recompute a zero-load
        # acceleration at the continuation boundary.
        runner.restore(restored_state)
    initial = state_payload(runner.state)
    vertices = [(0.5 * math.cos(2.0 * math.pi * index / vertex_count), 0.5 * math.sin(2.0 * math.pi * index / vertex_count)) for index in range(vertex_count)]
    participant = precice.Participant("Structure_0000", str(args.config), 0, 1)
    mesh = participant.set_mesh_vertices("Structure-Mesh", vertices)
    physical_checkpoint: PhysicalCheckpoint | None = None
    previous_force = initial_force
    accepted = 0
    attempts = 0
    restores = 0
    cumulative_work = restart_work
    cumulative_defect = restart_defect
    error: str | None = None
    try:
        initial_payload, initial_sha = displacement_payload(initial_interface_y, vertex_count)
        requested_initial = participant.requires_initial_data()
        if not requested_initial:
            raise RuntimeError("frozen parallel-implicit XML must request initial Displacement")
        participant.write_data("Structure-Mesh", "Displacement", mesh, initial_payload)
        append_jsonl(args.runtime / "events.jsonl", {
            "event": "initial_data", "physical_time_s": start, "local_time_s": 0.0,
            "payload_y_m": initial_interface_y, "payload_sha256": initial_sha, "initial_force_y_N": initial_force,
            "initial_state": initial, "restart": restart is not None,
            "acceleration_contract": "restored accepted acceleration" if restart is not None else "a0=(Fy0-K*y0-C*v0)/M",
        })
        participant.initialize()
        window_index = 1
        initial_runner_step = runner.state.step
        iteration = 0
        while participant.is_coupling_ongoing():
            if window_index > steps:
                raise RuntimeError("preCICE attempted to exceed the authorized accepted physical windows")
            wants_write = participant.requires_writing_checkpoint()
            wants_read = participant.requires_reading_checkpoint()
            if wants_read and physical_checkpoint is None:
                raise RuntimeError("preCICE requested rollback without an SDOF physical checkpoint")
            if wants_write:
                if physical_checkpoint is not None:
                    raise RuntimeError("preCICE requested a second checkpoint before committing the current window")
                physical_checkpoint = PhysicalCheckpoint.capture(
                    runner, previous_force, cumulative_work, cumulative_defect, accepted, f"window_{window_index:06d}"
                )
                payload = physical_checkpoint.payload()
                append_jsonl(args.runtime / "events.jsonl", {
                    "event": "checkpoint_write", "window_index": window_index, "iteration_index": iteration,
                    "physical_time_s": start + (window_index - 1) * dt, "checkpoint": payload,
                    "checkpoint_sha256": canonical(payload),
                })
            if physical_checkpoint is None:
                raise RuntimeError("implicit trial has no physical checkpoint")
            iteration += 1
            attempts += 1
            global_step = initial_runner_step + window_index
            local_time = global_step * dt
            physical_time = start + window_index * dt
            old_state = clone_state(runner.state)
            predicted = runner.predict(global_step, local_time, previous_force)
            enforce_emergency_protection(
                state=predicted, limits=protection, runtime=args.runtime, phase="predictor",
                physical_time_s=physical_time, window_index=window_index, iteration_index=iteration,
            )
            payload, payload_sha = displacement_payload(predicted.y, vertex_count)
            append_jsonl(args.runtime / "events.jsonl", {
                "event": "trial_write_displacement", "window_index": window_index, "iteration_index": iteration,
                "physical_output_time_s": physical_time, "local_output_time_s": local_time,
                "previous_accepted_force_y_N": previous_force, "checkpoint_id": physical_checkpoint.checkpoint_id,
                "predicted_state": state_payload(predicted), "payload_y_m": predicted.y, "payload_sha256": payload_sha,
                "time_layer_contract": "Fluid output t_n consumes this window's candidate y(t_n); initial data was y(t_0).",
            })
            participant.write_data("Structure-Mesh", "Displacement", mesh, payload)
            participant.advance(dt)
            force_values = participant.read_data("Structure-Mesh", "Force", mesh, 0.0)
            force_y, force_sha = force_sum_y(force_values, vertex_count)
            corrected, _ = runner.correct(global_step, local_time, force_y)
            old_energy = energy(old_state)
            new_energy = energy(corrected)
            work_increment = 0.5 * (previous_force + force_y) * (corrected.y - old_state.y)
            energy_defect = (new_energy - old_energy) - work_increment
            append_jsonl(args.runtime / "events.jsonl", {
                "event": "trial_read_force_and_correct", "window_index": window_index, "iteration_index": iteration,
                "physical_output_time_s": physical_time, "force_y_total_N": force_y, "force_payload_sha256": force_sha,
                "corrected_state": state_payload(corrected), "old_mechanical_energy_J": old_energy,
                "new_mechanical_energy_J": new_energy, "trapezoidal_fluid_work_increment_J": work_increment,
                "energy_balance_defect_J": energy_defect,
                "predictor_correction_y_m": corrected.y - predicted.y,
                "predictor_correction_v_mps": corrected.v - predicted.v,
            })
            enforce_emergency_protection(
                state=corrected, limits=protection, runtime=args.runtime, phase="corrector",
                physical_time_s=physical_time, window_index=window_index, iteration_index=iteration,
            )
            wants_read_after = participant.requires_reading_checkpoint()
            if wants_read_after:
                before = state_payload(runner.state)
                checkpoint_payload = physical_checkpoint.payload()
                physical_checkpoint.restore(runner)
                previous_force = physical_checkpoint.previous_force_y_N
                cumulative_work = physical_checkpoint.cumulative_fluid_work_J
                cumulative_defect = physical_checkpoint.cumulative_energy_defect_J
                accepted = physical_checkpoint.accepted_windows
                after = state_payload(runner.state)
                if after != checkpoint_payload["state"]:
                    raise RuntimeError("SDOF state differs after required physical rollback")
                restores += 1
                append_jsonl(args.runtime / "events.jsonl", {
                    "event": "checkpoint_restore", "window_index": window_index, "iteration_index": iteration,
                    "checkpoint_id": physical_checkpoint.checkpoint_id, "checkpoint_sha256": canonical(checkpoint_payload),
                    "before_restore_state": before, "after_restore_state": after,
                })
                continue
            cumulative_work += work_increment
            cumulative_defect += energy_defect
            previous_force = force_y
            accepted += 1
            append_jsonl(args.runtime / "events.jsonl", {
                "event": "window_commit", "window_index": window_index, "iteration_count": iteration,
                "physical_time_s": physical_time, "final_input_y_m": predicted.y,
                "accepted_state": state_payload(corrected), "force_y_total_N": force_y,
                "mechanical_energy_J": new_energy, "cumulative_fluid_work_J": cumulative_work,
                "cumulative_energy_balance_defect_J": cumulative_defect, "checkpoint_id": physical_checkpoint.checkpoint_id,
            })
            # Keep a small atomically-written snapshot for unattended runs;
            # the full event stream remains the authoritative record.
            if accepted % 1000 == 0 or accepted == 1:
                write_json(args.runtime / "progress.json", {
                    "status": "running", "accepted_windows": accepted,
                    "target_windows": steps, "physical_time_s": start + accepted * dt,
                    "state": state_payload(corrected), "force_y_total_N": force_y,
                    "mechanical_energy_J": new_energy, "checkpoint_id": physical_checkpoint.checkpoint_id,
                })
            physical_checkpoint = None
            window_index += 1
            iteration = 0
        if accepted != steps:
            raise RuntimeError(f"preCICE ended after {accepted}, not authorized {steps}, accepted windows")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            participant.finalize()
        except Exception as exc:
            error = error or f"preCICE finalize: {type(exc).__name__}: {exc}"
    summary = {
        "schema_version": "shiels-sdof-precice-participant-continuation-v1", "status": "completed" if error is None else "failed",
        "error": error, "accepted_windows": accepted, "trial_attempts": attempts, "checkpoint_restores": restores,
        "initial_force_y_N": initial_force, "initial_state": initial, "prior_accepted_windows": prior_accepted_windows,
        "last_accepted_physical_time_s": start + accepted * dt,
        "cumulative_fluid_work_J": cumulative_work, "cumulative_energy_balance_defect_J": cumulative_defect,
        "transport_identity_policy": "preCICE/transport IDs are not restored; only SDOF physical state is restored",
        "emergency_protection": protection,
    }
    write_json(args.runtime / "structure_summary.json", summary)
    write_json(args.runtime / "progress.json", {
        "status": "completed" if error is None else "failed",
        "accepted_windows": accepted, "target_windows": steps,
        "physical_time_s": start + accepted * dt, "error": error,
        "cumulative_fluid_work_J": cumulative_work,
        "cumulative_energy_balance_defect_J": cumulative_defect,
    })
    return 0 if error is None else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--vertex-count", type=int, default=40)
    args = parser.parse_args()
    if args.self_test:
        if args.output is None or args.output.exists():
            raise RuntimeError("self-test requires a new --output path")
        result = self_test()
        write_json(args.output, result)
        print(json.dumps({"status": result["status"], "output": str(args.output)}))
        return 0 if result["status"] == "PASS" else 1
    if args.config is None or args.runtime is None or args.contract is None:
        raise RuntimeError("real participant requires --config, --runtime and --contract")
    return run_participant(args)


if __name__ == "__main__":
    raise SystemExit(main())
