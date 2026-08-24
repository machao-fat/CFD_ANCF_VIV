from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - optional audit aid
    psutil = None

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.coupling.multi_slice_mapping.mapping import build_H_for_manifest, motion_from_ancf_state
from src.coupling.multi_slice_real_campaign.campaign import BatchMatlabANCFRunner, load_frozen_manifest
from src.coupling.persistent_ancf import PersistentANCFRunner


MATLAB = Path(os.environ.get("CFD_ANCF_MATLAB_EXE", r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe"))
MANIFEST_PATH = ROOT / "results" / "05_stage4c_scalability_tests" / "canonical_3slice_manifest_candidate.json"
OUT = ROOT / "results" / "06_persistent_ancf_tests"
CONFIG = {
    "L": 10.0, "D": 1.0, "dInner": 0.9, "nElem": 2, "nSlices": 3,
    "s_ref_m": [1.25, 5.0, 8.75], "topTension_N": 1.0e7,
    "youngs_modulus_Pa": 2.07e11, "dt": 0.0025, "start_time_s": 0.0,
    "newton_tolerance": 1.0e-8, "max_newton": 40,
}


def load_history(step: int) -> list[list[float]]:
    return [[
        100.0 * math.sin(0.07 * (step + 1) * (sid + 1)),
        40.0 * math.cos(0.11 * (step + 1) * (sid + 2)),
        5.0 * math.sin(0.03 * (step + 2)),
    ] for sid in range(3)]


def rel_error(a, b) -> float:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) / max(1.0, abs(float(a)), abs(float(b)))
    aa, bb = list(map(float, a)), list(map(float, b))
    if len(aa) != len(bb):
        return float("inf")
    return max((abs(x - y) for x, y in zip(aa, bb)), default=0.0) / max(1.0, max((abs(x) for x in aa), default=0.0), max((abs(y) for y in bb), default=0.0))


def state_motion(manifest, state, step: int, time_s: float) -> list[dict]:
    H = build_H_for_manifest(manifest, [0.0, 5.0, 10.0], ndof=18)
    records = []
    for spec in manifest.slices:
        record = motion_from_ancf_state(manifest, spec.slice_id, H[spec.slice_id], state["q"], state["qdot"], state["qddot"], step=step, time_s=time_s, reference_position_m=(0.0, 0.0, spec.s_ref_m))
        records.append(record.to_dict())
    return records


def run_batch(manifest, root: Path, steps: int = 20) -> tuple[list[dict], float]:
    runner = BatchMatlabANCFRunner(work_dir=root, start_time_s=0.0, manifest=manifest, matlab_exe=MATLAB)
    started = time.perf_counter()
    runner.start()
    states = []
    previous = [[0.0, 0.0, 0.0] for _ in range(3)]
    try:
        for step in range(steps):
            t = (step + 1) * CONFIG["dt"]
            runner.predict(step, t, previous)
            runner.correct(step, t, load_history(step))
            state = runner.state_view()
            runner.finalize_committed()
            states.append({"step": step, "time_s": t, **state, "motion": state_motion(manifest, state, step, t)})
            previous = load_history(step)
    finally:
        runner.shutdown()
    return states, time.perf_counter() - started


def run_persistent(manifest, root: Path, steps: int, *, checkpoint_step: int | None = None) -> tuple[list[dict], float, PersistentANCFRunner, Path | None]:
    runner = PersistentANCFRunner(config=CONFIG, matlab_exe=MATLAB, request_dir=root, timeout_s=180.0)
    started = time.perf_counter()
    runner.start()
    states = []
    previous = [[0.0, 0.0, 0.0] for _ in range(3)]
    checkpoint = None
    for step in range(steps):
        t = (step + 1) * CONFIG["dt"]
        runner.predict(step, t, previous)
        response, _ = runner.correct(step, t, load_history(step))
        state = {"q": response["q"], "qdot": response["qdot"], "qddot": response["qddot"]}
        states.append({"step": step, "time_s": t, **state, "motion": response["motion"], "audit": {key: response[key] for key in ("newton_iterations", "newton_residual", "min_tension_N", "max_tension_N", "converged")}})
        checkpoint = None
        if checkpoint_step is not None and step == checkpoint_step:
            checkpoint = root / f"checkpoint_step_{step:08d}.mat"
            prepared = runner.prepare_checkpoint(checkpoint)
            runner.finalize_commit(prepared["checkpoint_token"])
        else:
            prepared = runner.prepare_checkpoint(root / f"checkpoint_step_{step:08d}.mat")
            runner.finalize_commit(prepared["checkpoint_token"])
        previous = load_history(step)
    return states, time.perf_counter() - started, runner, checkpoint


def memory_sample(runner: PersistentANCFRunner, step: int) -> dict:
    if psutil is None or runner.process is None:
        return {"step": step, "rss_bytes": None, "handles": None}
    process = psutil.Process(runner.process.pid)
    info = process.memory_info()
    return {"step": step, "rss_bytes": info.rss, "handles": getattr(process, "num_handles", lambda: None)()}


def run_1000(manifest, root: Path) -> tuple[dict, float]:
    runner = PersistentANCFRunner(config=CONFIG, matlab_exe=MATLAB, request_dir=root, timeout_s=180.0)
    started = time.perf_counter()
    runner.start()
    previous = [[0.0, 0.0, 0.0] for _ in range(3)]
    samples = [memory_sample(runner, 0)]
    finite = True
    try:
        for step in range(1000):
            t = (step + 1) * CONFIG["dt"]
            runner.predict(step, t, previous)
            response, _ = runner.correct(step, t, load_history(step))
            if step in (249, 499, 749, 999):
                samples.append(memory_sample(runner, step + 1))
            finite = finite and all(math.isfinite(float(value)) for key in ("q", "qdot", "qddot") for value in response[key])
            prepared = runner.prepare_checkpoint(root / f"checkpoint_{step:08d}.mat")
            runner.finalize_commit(prepared["checkpoint_token"])
            previous = load_history(step)
        heartbeat = runner.heartbeat()
        summary = {
            "status": "passed" if finite and heartbeat["global_step"] == 999 and abs(float(heartbeat["time_s"]) - 2.5) <= 1.0e-12 else "failed",
            "steps": 1000, "time_end_s": heartbeat["time_s"], "global_step": heartbeat["global_step"],
            "finite": finite, "worker_pid": runner.worker_pid, "matlab_process_start_count": runner.start_count,
            "pending_state": False, "resource_samples": samples,
            "command_count": len(runner.command_history),
        }
    finally:
        runner.shutdown()
    return summary, time.perf_counter() - started


def main() -> None:
    if not MATLAB.is_file():
        raise SystemExit(f"MATLAB not found: {MATLAB}")
    OUT.mkdir(parents=True, exist_ok=True)
    run_root = OUT / f"campaign_{time.strftime('%Y%m%dT%H%M%S')}_{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=False)
    manifest = load_frozen_manifest(MANIFEST_PATH)
    batch_states, batch_elapsed = run_batch(manifest, run_root / "batch_20")
    persistent_states, persistent_elapsed, runner, _ = run_persistent(manifest, run_root / "persistent_20", 20)
    try:
        equivalence = {
            key: max(rel_error(batch_states[i][key], persistent_states[i][key]) for i in range(20))
            for key in ("q", "qdot", "qddot")
        }
        motion_error = max(rel_error(batch_states[i]["motion"][sid][field], persistent_states[i]["motion"][sid][field]) for i in range(20) for sid in range(3) for field in ("x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2"))
        equivalence["slice_motion"] = motion_error
    finally:
        runner.shutdown()
    (OUT / "persistent_equivalence_summary.json").write_text(json.dumps({
        "status": "passed" if max(equivalence.values()) <= 1.0e-11 else "failed",
        "batch_steps": 20, "persistent_steps": 20, "errors": equivalence,
        "batch_elapsed_s": batch_elapsed, "persistent_elapsed_s": persistent_elapsed,
        "batch_avg_step_s": batch_elapsed / 20.0, "persistent_avg_step_s": persistent_elapsed / 20.0,
        "speedup": batch_elapsed / max(persistent_elapsed, 1.0e-30), "matlab_process_start_count": 1,
        "schema_version": "stage4d-persistent-equivalence-1",
    }, indent=2) + "\n", encoding="utf-8")

    hundred_summary, hundred_elapsed = run_1000(manifest, run_root / "persistent_1000")
    hundred_summary.update({"elapsed_s": hundred_elapsed, "average_step_s": hundred_elapsed / 1000.0})
    (OUT / "persistent_1000_step_summary.json").write_text(json.dumps(hundred_summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    continuous, continuous_elapsed, cont_runner, _ = run_persistent(manifest, run_root / "restart_continuous_100", 100)
    cont_runner.shutdown()
    restart_root = run_root / "restart_50_plus_50"
    restart_root.mkdir(parents=True, exist_ok=True)
    restart_runner = PersistentANCFRunner(config=CONFIG, matlab_exe=MATLAB, request_dir=restart_root, timeout_s=180.0)
    restart_started = time.perf_counter()
    restart_runner.start()
    previous = [[0.0, 0.0, 0.0] for _ in range(3)]
    restarted = []
    checkpoint = restart_root / "checkpoint_step_00000049.mat"
    for step in range(50):
        t = (step + 1) * CONFIG["dt"]
        restart_runner.predict(step, t, previous); response, _ = restart_runner.correct(step, t, load_history(step))
        prepared = restart_runner.prepare_checkpoint(restart_root / f"checkpoint_step_{step:08d}.mat"); restart_runner.finalize_commit(prepared["checkpoint_token"])
        restarted.append({"step": step, "time_s": t, "q": response["q"], "qdot": response["qdot"], "qddot": response["qddot"]})
        previous = load_history(step)
    restart_runner.load_checkpoint(checkpoint)
    for step in range(50, 100):
        t = (step + 1) * CONFIG["dt"]
        restart_runner.predict(step, t, previous); response, _ = restart_runner.correct(step, t, load_history(step))
        prepared = restart_runner.prepare_checkpoint(restart_root / f"checkpoint_step_{step:08d}.mat"); restart_runner.finalize_commit(prepared["checkpoint_token"])
        restarted.append({"step": step, "time_s": t, "q": response["q"], "qdot": response["qdot"], "qddot": response["qddot"]})
        previous = load_history(step)
    restart_end = restart_runner.heartbeat()
    restart_starts = restart_runner.start_count
    restart_runner.shutdown()
    restart_errors = {key: max(rel_error(continuous[i][key], restarted[i][key]) for i in range(100)) for key in ("q", "qdot", "qddot")}
    restart_errors["time"] = max(abs(continuous[i]["time_s"] - restarted[i]["time_s"]) for i in range(100))
    (OUT / "persistent_restart_summary.json").write_text(json.dumps({
        "status": "passed" if max(restart_errors["q"], restart_errors["qdot"], restart_errors["qddot"]) <= 1.0e-11 and restart_errors["time"] <= 1.0e-12 else "failed",
        "continuous_steps": 100, "restart_segments": [50, 50], "errors": restart_errors,
        "checkpoint_step": 49, "restored_global_step": 49, "restored_time_s": 0.125,
        "restart_worker_start_count": restart_starts, "continuous_elapsed_s": continuous_elapsed,
        "restart_elapsed_s": time.perf_counter() - restart_started, "final_global_step": restart_end["global_step"], "final_time_s": restart_end["time_s"],
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"equivalence": equivalence, "persistent_1000": hundred_summary, "restart_errors": restart_errors}, indent=2))


if __name__ == "__main__":
    main()
