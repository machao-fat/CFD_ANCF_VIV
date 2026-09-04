"""Read-only C++ replay to reconstruct the Stage211 ANCF state at step1439.

Stage211 predates portable restart checkpoints. This one-time recovery uses
only its accepted force journal and a fresh C++ worker. It never starts
MATLAB, OpenFOAM, WSL, or CFD and never writes into Stage211.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker, _fixture
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as base

STAGE_ID = "stage4f_d_cpp_worker_to6s_source_reconstruction_v1"
RUN_ID = "cpp_worker_to6s_source_replay_001"
CASE_ID = "cpp_worker_to6s_source_replay_case_001"
PARENT_STAGE_ID = "stage4f_d_cpp_worker_long_window_v1"
PARENT_RUN_ID = "cpp_worker_long_window_003"
PARENT_RESULTS = PROJECT / "results/211_cpp_worker_long_window_v1_retry2"
PARENT_GATE = PARENT_RESULTS / "stage4f_d_cpp_worker_long_window_v1_retry2_gate.json"
PARENT_SOURCE = PROJECT / "runtime/cpp_worker_long_window_v1/source_derivation_001/continuation_source_step00000639_v1.json"
PARENT_SOURCE_SHA256 = "e88feafb3efd4b9428ac04cd3d207aa0d5288a9a35c93e5a6bc9fad034c4612a"
PARENT_CHECKPOINT = PROJECT / "runtime/cpp_worker_long_window_v1/long_window_003/checkpoint/checkpoint_00001439.json"
PARENT_CHECKPOINT_SHA256 = "17d71a2a0f03dae04d57f1afbade7299842c1e0bdf633a3b92ff070ecaf982d3"
RUNTIME = PROJECT / "runtime/cpp_worker_to6s_v1/source_derivation_1439"
RESULTS = PROJECT / "results/213_cpp_worker_to6s_source_reconstruction_v1"
OUTPUT_SOURCE = RUNTIME / "continuation_source_step00001439_v1.json"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_bytes(_canonical(value))
    os.replace(temporary, path)


def _finite_state(state: dict[str, list[float]]) -> None:
    if set(state) != {"q", "qdot", "qddot"}:
        raise RuntimeError("replayed state schema is incomplete")
    if (len({len(values) for values in state.values()}) != 1 or
            any(not math.isfinite(float(value)) for values in state.values() for value in values)):
        raise RuntimeError("replayed state is non-finite or dimensionally inconsistent")


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("reconstruction destination exists; refusing retry")
    if _sha256(PARENT_SOURCE) != PARENT_SOURCE_SHA256 or _sha256(PARENT_CHECKPOINT) != PARENT_CHECKPOINT_SHA256:
        raise RuntimeError("Stage211 source/checkpoint SHA-256 mismatch")
    gate = json.loads(PARENT_GATE.read_text(encoding="utf-8"))
    if gate.get("status") != "pass":
        raise RuntimeError("Stage211 parent Gate is not pass")
    summary = json.loads((PARENT_RESULTS / "confirm_summary.json").read_text(encoding="utf-8"))
    records = sorted(summary.get("records", []), key=lambda row: int(row.get("global_step", -1)))
    if [int(row.get("global_step", -1)) for row in records] != list(range(640, 1440)):
        raise RuntimeError("Stage211 force journal is not exactly committed steps 640..1439")

    model, _q, _qdot, _qddot, base_load = _fixture()
    model = base.normalize_model(model)
    mass_matrix = base._source_mass_matrix()
    worker = KernelWorker(base.WORKER_EXE, RUNTIME / "process", RUN_ID, CASE_ID,
                          expected_model_contract_sha256=base.EXPECTED_MODEL_CONTRACT_SHA256)
    adapter = CppKernelCampaignAdapter.from_checkpoint(
        worker=worker, model=model, request_factory=KernelStepRequest,
        checkpoint=PARENT_SOURCE, expected_sha256=PARENT_SOURCE_SHA256,
        run_id=RUN_ID, case_id=CASE_ID, dt_s=0.00125, base_load=base_load,
        slice_count=3, mass_matrix=mass_matrix,
        expected_model_contract_sha256=base.EXPECTED_MODEL_CONTRACT_SHA256)
    rows: list[dict[str, Any]] = []
    state: dict[str, list[float]] | None = None
    failure: str | None = None
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        adapter.start()
        for row in records:
            step, time_s = int(row["global_step"]), float(row["time_s"])
            metadata = row.get("checkpoint_metadata")
            applied = metadata.get("applied_slice_forces_N") if isinstance(metadata, dict) else None
            if not isinstance(applied, list) or len(applied) != 3:
                raise RuntimeError(f"step {step} applied-force journal is incomplete")
            force = tuple(tuple(float(value) for value in item) for item in applied)
            prediction, _ = adapter.predict(step, time_s, force)
            correction, _ = adapter.correct(step, time_s, force)
            adapter.finalize_committed()
            state = adapter.state_view()
            _finite_state(state)
            rows.append({"global_step": step, "time_s": time_s,
                         "integer_tick": 2_207_500_000 + (step - 559) * 1_250_000,
                         "prediction_payload_hash": prediction["payload_hash"],
                         "correction_payload_hash": correction["payload_hash"],
                         "state_sha256": hashlib.sha256(_canonical(state)).hexdigest(),
                         "finite_value_audit": True})
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            adapter.stop()
        except Exception as exc:
            failure = failure or f"worker cleanup failed: {exc}"
    residual = int(adapter.owned_residual)
    passed = failure is None and state is not None and len(rows) == 800 and residual == 0
    if passed:
        last_metadata = records[-1]["checkpoint_metadata"]
        source = {"schema_version": "stage100_cpp_continuation_source_v1", "status": "committed",
                  "step": 1439, "time_s": 3.3075, "time_tick": 3_307_500_000,
                  "structure": state,
                  "applied_slice_forces_N": last_metadata["applied_slice_forces_N"],
                  "next_applied_slice_forces_N": last_metadata["next_applied_slice_forces_N"],
                  "parent": {"stage_id": PARENT_STAGE_ID, "run_id": PARENT_RUN_ID,
                             "barrier_checkpoint": str(PARENT_CHECKPOINT), "parent_checkpoint_step": 1439},
                  "source_parent_sha256": PARENT_CHECKPOINT_SHA256,
                  "reconstruction": {"stage_id": STAGE_ID, "run_id": RUN_ID,
                                     "replayed_steps": "640..1439", "replay_worker_startup": 1,
                                     "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                                     "owned_residual": residual}}
        _write(OUTPUT_SOURCE, source)
    evidence = {"gate": "STAGE4F_D_CPP_WORKER_TO6S_SOURCE_RECONSTRUCTION_V1_GATE: pass" if passed else "STAGE4F_D_CPP_WORKER_TO6S_SOURCE_RECONSTRUCTION_V1_GATE: do_not_pass",
                "status": "pass" if passed else "do_not_pass", "parent_stage": PARENT_STAGE_ID,
                "parent_checkpoint": str(PARENT_CHECKPOINT), "parent_checkpoint_sha256": PARENT_CHECKPOINT_SHA256,
                "replayed_steps": len(rows), "replayed_step_range": [640, 1439], "failure": failure,
                "owned_residual": residual,
                "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                "output_source": str(OUTPUT_SOURCE) if passed else None,
                "output_source_sha256": _sha256(OUTPUT_SOURCE) if passed else None,
                "old_evidence_modified": False, "next_real_segment_started": False}
    _write(RESULTS / "source_reconstruction_gate.json", evidence)
    _write(RESULTS / "source_replay_audit.json", {"rows": rows, "failure": failure,
                                                     "parent_source_read_only": str(PARENT_SOURCE)})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
