from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from .real_runner import RealRunnerSession


CONFIG: dict[str, Any] = {
    "L": 10.0,
    "D": 1.0,
    "dInner": 0.9,
    "nElem": 2,
    "nSlices": 3,
    "s_ref_m": [1.25, 5.0, 8.75],
    "topTension_N": 1.0e7,
    "youngs_modulus_Pa": 2.07e11,
    "dt": 0.0025,
    "start_time_s": 0.0,
    "newton_tolerance": 1.0e-8,
    "max_newton": 40,
}
ZERO_LOAD = [[0.0, 0.0, 0.0] for _ in range(3)]
TRANSVERSE_LOAD = [[0.0, 10.0, 0.0] for _ in range(3)]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_finite(value: Any, label: str = "value") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_finite(item, f"{label}.{key}")
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _assert_finite(item, f"{label}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise RuntimeError(f"{label} contains NaN/Inf")


def _relative_max(before: Mapping[str, list[float]], after: Mapping[str, list[float]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in ("q", "qdot", "qddot"):
        lhs = before[key]
        rhs = after[key]
        result[key] = max((abs(float(a) - float(b)) / max(1.0, abs(float(a)), abs(float(b))) for a, b in zip(lhs, rhs)), default=0.0)
    return result


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def run_worker_smoke(*, project_root: str | Path, output_dir: str | Path, matlab_exe: str | Path) -> dict[str, Any]:
    project = Path(project_root).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    primary: RealRunnerSession | None = None
    restart: RealRunnerSession | None = None
    primary_summary: dict[str, Any] | None = None
    restart_summary: dict[str, Any] | None = None
    checkpoint: Path | None = None
    result: dict[str, Any] = {
        "schema_version": "stage4e-b1-v3.1.2-real-worker-smoke-1.0.0",
        "status": "failed",
        "purpose": "real_R2021b_persistent_ANCF_worker_smoke",
        "matlab_probe_rerun_count": 0,
        "config": CONFIG,
        "finite_state": False,
        "predict_completed": False,
        "correct_completed": False,
        "checkpoint_completed": False,
        "restart_completed": False,
        "silent_restart_detected": False,
    }
    try:
        primary = RealRunnerSession(project_root=project, config=CONFIG, matlab_exe=matlab_exe, purpose="v3_1_2_worker_smoke_primary")
        start_response = primary.start()
        initial = primary.runner.state_view()
        _assert_finite(initial, "initial_state")
        result["finite_state"] = True
        predicted, _ = primary.runner.predict(0, CONFIG["dt"], TRANSVERSE_LOAD)
        _assert_finite(predicted, "predict_response")
        result["predict_completed"] = True
        corrected, motion = primary.runner.correct(0, CONFIG["dt"], ZERO_LOAD)
        _assert_finite(corrected, "correct_response")
        _assert_finite(motion, "motion")
        if not corrected.get("converged"):
            raise RuntimeError("Newton correction did not converge")
        result["correct_completed"] = True
        result["newton"] = {
            "iterations": corrected.get("newton_iterations"),
            "residual": corrected.get("newton_residual"),
            "converged": corrected.get("converged"),
            "min_tension_N": corrected.get("min_tension_N"),
            "max_tension_N": corrected.get("max_tension_N"),
        }
        primary.runner.prepare_checkpoint(primary.root / "checkpoints" / "smoke_precommit.mat")
        primary.runner.finalize_commit()
        checkpoint = primary.root / "checkpoints" / "smoke_committed.mat"
        primary.runner.save_checkpoint(checkpoint)
        if not checkpoint.is_file():
            raise RuntimeError("checkpoint file was not created")
        checkpoint_state = primary.runner.state_view()
        result["checkpoint_completed"] = True
        result["checkpoint_path"] = str(checkpoint)
        result["checkpoint_sha256"] = _file_sha256(checkpoint)
        primary.close()
        primary_summary = primary.summary
        restart = RealRunnerSession(project_root=project, config=CONFIG, matlab_exe=matlab_exe, purpose="v3_1_2_worker_smoke_restart")
        restart.start()
        restart.runner.load_checkpoint(checkpoint)
        loaded_state = restart.runner.state_view()
        _assert_finite(loaded_state, "loaded_state")
        restart_errors = _relative_max(checkpoint_state, loaded_state)
        result["checkpoint_restart_relative_errors"] = restart_errors
        result["checkpoint_restart_max_relative_error"] = max(restart_errors.values())
        if result["checkpoint_restart_max_relative_error"] > 1.0e-11:
            raise RuntimeError("checkpoint restart relative error exceeds 1e-11")
        result["restart_completed"] = True
        if restart.runner.start_count != 1:
            result["silent_restart_detected"] = True
            raise RuntimeError("runner start count changed unexpectedly")
        restart.close()
        restart_summary = restart.summary
        result["status"] = "passed"
        result["start_response"] = {"action": start_response.get("action"), "global_step": start_response.get("global_step")}
    except BaseException as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    finally:
        if primary is not None and not primary.closed:
            primary.close()
        if restart is not None and not restart.closed:
            restart.close()
        primary_summary = primary_summary or (primary.summary if primary is not None and primary.closed else None)
        restart_summary = restart_summary or (restart.summary if restart is not None and restart.closed else None)
    result["primary_session"] = primary_summary
    result["restart_session"] = restart_summary
    result["owned_residual_count"] = sum(int((item or {}).get("owned_residual_count", 0)) for item in (primary_summary, restart_summary) if item)
    result["owned_residual_pids"] = [pid for item in (primary_summary, restart_summary) if item for pid in item.get("owned_residual_pids", [])]
    _write(output / "real_worker_smoke.json", result)
    _write(output / "real_worker_checkpoint_restart.json", {
        "schema_version": "stage4e-b1-v3.1.2-checkpoint-restart-1.0.0",
        "status": "passed" if result["restart_completed"] else "failed",
        "checkpoint_path": result.get("checkpoint_path"),
        "checkpoint_sha256": result.get("checkpoint_sha256"),
        "relative_errors": result.get("checkpoint_restart_relative_errors"),
        "max_relative_error": result.get("checkpoint_restart_max_relative_error"),
        "threshold": 1.0e-11,
        "primary_run_id": (primary_summary or {}).get("run_id"),
        "restart_run_id": (restart_summary or {}).get("run_id"),
    })
    _write(output / "worker_process_tree.json", {
        "schema_version": "stage4e-b1-v3.1.2-worker-process-tree-1.0.0",
        "sessions": [item for item in (primary_summary, restart_summary) if item],
    })
    _write(output / "worker_protocol_trace.json", {
        "schema_version": "stage4e-b1-v3.1.2-worker-protocol-trace-1.0.0",
        "sessions": [
            {"run_id": item.get("run_id"), "purpose": item.get("purpose"), "command": item.get("command"), "event_log_path": item.get("event_log_path"), "event_log_sha256": item.get("event_log_sha256")}
            for item in (primary_summary, restart_summary) if item
        ],
        "required_actions": ["initialize", "predict", "correct", "prepare_checkpoint", "finalize_commit", "save_checkpoint", "shutdown", "load_checkpoint"],
    })
    _write(output / "worker_cleanup_audit.json", {
        "schema_version": "stage4e-b1-v3.1.2-worker-cleanup-audit-1.0.0",
        "sessions": [
            {"run_id": item.get("run_id"), "cleanup_actions": item.get("cleanup_actions"), "runner_cleanup_audit": item.get("runner_cleanup_audit"), "owned_residual_pids": item.get("owned_residual_pids", [])}
            for item in (primary_summary, restart_summary) if item
        ],
        "owned_residual_count": result["owned_residual_count"],
    })
    return result

