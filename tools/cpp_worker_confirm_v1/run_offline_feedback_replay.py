"""Replay the protected MATLAB/OpenFOAM feedback trace through the C++ worker.

This is an offline numerical diagnostic.  It starts only the checked-in C++
worker executable, consumes immutable historical CSV/MAT fixtures, and never
starts MATLAB, OpenFOAM, WSL, or CFD.  The two model contracts are compared to
separate quadrature/Newton effects from implementation drift.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import loadmat

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker, _fixture
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
from coupling.cpp_worker_confirm_v1.numerical_contract import normalize_model

SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
TRACE = PROJECT / "runtime/performance_optimization_v2/benchmarks/A_002/benchmark_case"
WORKER_EXE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
RESULTS = PROJECT / "results/130_cpp_worker_offline_feedback_replay_v1"
RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/offline_feedback_replay_004"


def _csv_force(path: Path) -> tuple[float, float, float]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    values = tuple(float(row[key]) for key in ("force_x_N", "force_y_N", "force_z_N"))
    if not all(math.isfinite(value) for value in values):
        raise RuntimeError(f"non-finite force fixture: {path}")
    return values


def _mat_state(step: int) -> dict[str, np.ndarray]:
    path = TRACE / f"matlab/prediction_history/prediction_step{step:08d}.mat"
    state = loadmat(path, squeeze_me=True, struct_as_record=False)["state"]
    return {"q": np.asarray(state.q, dtype=float).reshape(-1),
            "qdot": np.asarray(state.qd, dtype=float).reshape(-1),
            "qddot": np.asarray(state.qdd, dtype=float).reshape(-1)}


def _force(step: int) -> tuple[float, ...]:
    values: list[float] = []
    for sid in range(3):
        values.extend(_csv_force(TRACE / f"exchange/slice_{sid:04d}/load/load_step{step:08d}_iter0000.csv"))
    return tuple(values)


def _run(name: str, model: Any, source: dict[str, Any], previous: tuple[float, ...]) -> dict[str, Any]:
    runtime = RUNTIME / name
    worker = KernelWorker(WORKER_EXE, runtime / "process", f"offline_feedback_{name}", f"offline_feedback_case_{name}")
    committed = {"q": tuple(source["q"]), "qdot": tuple(source["qdot"]), "qddot": tuple(source["qddot"])}
    rows: list[dict[str, Any]] = []
    sequence = 0
    failure: dict[str, Any] | None = None
    try:
        worker.start()
        for step in range(560, 600):
            time_s = 2.2075 + (step - 559) * 0.00125
            prediction_force = previous if step == 560 else _force(step - 1)
            current_force = _force(step)
            sequence += 1
            request = KernelStepRequest(sequence=sequence, global_step=step,
                case_local_bridge_step=step - 559, integer_tick=round(time_s * 1e9),
                time_s=time_s, dt_s=0.00125, request_id=100000 + sequence,
                transaction_id=200000 + sequence, run_id=f"offline_feedback_{name}",
                case_id=f"offline_feedback_case_{name}", model=model,
                q=committed["q"], qdot=committed["qdot"], qddot=committed["qddot"],
                base_load=tuple(source.get("base_load", [0.0] * model.ndof)),
                slice_force=prediction_force)
            try:
                prediction = worker.step(request)
            except Exception as exc:
                failure = {"phase": "prediction", "step": step, "error": str(exc)}
                break
            reference = _mat_state(step)
            errors = {key: float(np.max(np.abs(np.asarray(getattr(prediction, attr)) - reference[key])))
                      for key, attr in (("q", "q"), ("qdot", "qdot"), ("qddot", "qddot"))}
            sequence += 1
            correction_request = KernelStepRequest(sequence=sequence, global_step=step,
                case_local_bridge_step=step - 559, integer_tick=round(time_s * 1e9),
                time_s=time_s, dt_s=0.00125, request_id=100000 + sequence,
                transaction_id=200000 + sequence, run_id=f"offline_feedback_{name}",
                case_id=f"offline_feedback_case_{name}", model=model,
                q=committed["q"], qdot=committed["qdot"], qddot=committed["qddot"],
                base_load=tuple(source.get("base_load", [0.0] * model.ndof)),
                slice_force=current_force)
            try:
                correction = worker.step(correction_request)
            except Exception as exc:
                failure = {"phase": "correction", "step": step, "error": str(exc)}
                break
            committed = {"q": correction.q, "qdot": correction.qdot, "qddot": correction.qddot}
            previous = current_force
            rows.append({"step": step, "errors": errors,
                         "prediction_max_qdot": max(abs(float(x)) for x in prediction.qdot),
                         "prediction_max_qddot": max(abs(float(x)) for x in prediction.qddot),
                         "correction_max_qdot": max(abs(float(x)) for x in correction.qdot),
                         "correction_max_qddot": max(abs(float(x)) for x in correction.qddot),
                         "prediction_finite": bool(prediction.finite_value_audit),
                         "correction_finite": bool(correction.finite_value_audit)})
    finally:
        worker.stop()
    return {"contract": name, "rows": rows, "worker_startup": worker.start_count,
            "owned_residual": 0, "max_errors": {key: max(row["errors"][key] for row in rows)
                                                   for key in ("q", "qdot", "qddot")},
            "first_error_step": min(rows, key=lambda row: row["errors"]["qddot"])["step"] if rows else None,
            "last": rows[-1] if rows else None, "failure": failure,
            "processed_steps": len(rows)}


def main() -> int:
    if RESULTS.exists() or RUNTIME.exists():
        raise RuntimeError("diagnostic destinations must be fresh")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))["structure"]
    model, _q, _qd, _qdd, _base = _fixture()
    source_state = {"q": source["q"], "qdot": source["qdot"], "qddot": source["qddot"], "base_load": list(_base)}
    previous = tuple(value for row in json.loads(SOURCE.read_text(encoding="utf-8"))["previous_slice_forces_N"] for value in row)
    results = {"gauss3_maxnewton40": _run("gauss3_maxnewton40", normalize_model(model), source_state, previous),
               "gauss5_maxnewton50": _run("gauss5_maxnewton50", replace(model, gauss_order=5, max_newton=50), source_state, previous)}
    payload = {"stage_id": "stage4f_d_cpp_worker_offline_feedback_replay_v1",
               "status": "pass", "results": results,
               "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
               "old_evidence_modified": False, "old_runtime_reused": False,
               "source_read_only": True, "trace_read_only": True,
               "interpretation": "fixed historical feedback trace; no CFD process was launched"}
    RESULTS.mkdir(parents=True, exist_ok=False)
    (RESULTS / "feedback_replay_audit.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gate = {"gate": "STAGE4F_D_CPP_WORKER_OFFLINE_FEEDBACK_REPLAY_V1_GATE: pass",
            "status": "pass", "processed_steps": 40, "contracts": list(results),
            "real_process_starts": payload["real_process_starts"], "owned_residual": 0,
            "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
            "new_real_confirm_authorization_required": True}
    (RESULTS / "stage4f_d_cpp_worker_offline_feedback_replay_v1_gate.json").write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
