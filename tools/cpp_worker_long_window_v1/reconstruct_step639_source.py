"""Reconstruct the exact C++ ANCF state at accepted Stage204 step639.

Stage204 retained an immutable barrier checkpoint and complete committed force
journal but, by design, not a restartable ANCF state.  This read-only replay
derives that state using the same qualified C++ worker.  It starts no MATLAB,
OpenFOAM, WSL, or CFD process.
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


STAGE_ID = "stage4f_d_cpp_worker_long_window_source_reconstruction_v1"
RUN_ID = "cpp_worker_long_window_source_replay_001"
CASE_ID = "cpp_worker_long_window_source_replay_case_001"
PARENT_STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v17"
PARENT_RUN_ID = "cpp_worker_persistent_ipc_confirm_017"
PARENT_RESULTS = PROJECT / "results/204_cpp_worker_persistent_ipc_confirm_v17"
PARENT_GATE = PARENT_RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json"
PARENT_SOURCE = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/continuation_source_step00000599_v1.json"
PARENT_SOURCE_SHA256 = "21e308fea2073cc9b1cafcc075262e433bcc36df6100fbe282b184f0236aa995"
ACCEPTED_BARRIER_CHECKPOINT = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_017/checkpoint/checkpoint_00000639.json"
ACCEPTED_BARRIER_SHA256 = "87953ea5a40ec868dc589b8a0af6f54278f19b55eb86d4247c61c4ba7e742a9f"
DERIVATION_ROOT = PROJECT / "runtime/cpp_worker_long_window_v1/source_derivation_001"
OUTPUT_SOURCE = DERIVATION_ROOT / "continuation_source_step00000639_v1.json"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


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
    if len({len(values) for values in state.values()}) != 1 or any(
        not math.isfinite(float(value)) for values in state.values() for value in values
    ):
        raise RuntimeError("replayed state is non-finite or dimensionally inconsistent")


def main() -> int:
    if DERIVATION_ROOT.exists():
        raise RuntimeError("source derivation destination already exists; refusing retry")
    if _sha256(ACCEPTED_BARRIER_CHECKPOINT) != ACCEPTED_BARRIER_SHA256:
        raise RuntimeError("accepted Stage204 barrier checkpoint hash mismatch")
    parent_gate = json.loads(PARENT_GATE.read_text(encoding="utf-8"))
    if parent_gate.get("status") != "pass":
        raise RuntimeError("Stage204 parent Gate is not pass")
    summary = json.loads((PARENT_RESULTS / "confirm_summary.json").read_text(encoding="utf-8"))
    records = sorted(summary.get("records", []), key=lambda row: int(row.get("global_step", -1)))
    if [int(row.get("global_step", -1)) for row in records] != list(range(600, 640)):
        raise RuntimeError("Stage204 force journal is not exactly committed steps 600..639")

    model, _q, _qdot, _qddot, base_load = _fixture()
    model = base.normalize_model(model)
    mass_matrix = base._source_mass_matrix()
    worker = KernelWorker(base.WORKER_EXE, DERIVATION_ROOT / "process", RUN_ID, CASE_ID,
                          expected_model_contract_sha256=base.EXPECTED_MODEL_CONTRACT_SHA256)
    adapter = CppKernelCampaignAdapter.from_checkpoint(
        worker=worker, model=model, request_factory=KernelStepRequest,
        checkpoint=PARENT_SOURCE, expected_sha256=PARENT_SOURCE_SHA256,
        run_id=RUN_ID, case_id=CASE_ID, dt_s=0.00125, base_load=base_load,
        slice_count=3, mass_matrix=mass_matrix,
        expected_model_contract_sha256=base.EXPECTED_MODEL_CONTRACT_SHA256,
    )
    rows: list[dict[str, Any]] = []
    state: dict[str, list[float]] | None = None
    failure: str | None = None
    try:
        DERIVATION_ROOT.mkdir(parents=True, exist_ok=True)
        adapter.start()
        for row in records:
            step = int(row["global_step"])
            time_s = float(row["time_s"])
            metadata = row.get("checkpoint_metadata")
            if not isinstance(metadata, dict):
                raise RuntimeError(f"step {step} checkpoint metadata is absent")
            applied = metadata.get("applied_slice_forces_N")
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
    passed = failure is None and state is not None and len(rows) == 40 and residual == 0
    if passed:
        last_metadata = records[-1]["checkpoint_metadata"]
        source = {
            "schema_version": "stage100_cpp_continuation_source_v1", "status": "committed",
            "step": 639, "time_s": 2.3075, "time_tick": 2_307_500_000,
            "structure": state,
            # Preserve the established source convention: this is the force
            # committed at the source step, not a speculative next-step load.
            "applied_slice_forces_N": last_metadata["applied_slice_forces_N"],
            "next_applied_slice_forces_N": last_metadata["next_applied_slice_forces_N"],
            "parent": {"stage_id": PARENT_STAGE_ID, "run_id": PARENT_RUN_ID,
                       "barrier_checkpoint": str(ACCEPTED_BARRIER_CHECKPOINT),
                       "parent_checkpoint_step": 639},
            "source_parent_sha256": ACCEPTED_BARRIER_SHA256,
            "reconstruction": {"stage_id": STAGE_ID, "run_id": RUN_ID,
                               "replayed_steps": "600..639", "replay_worker_startup": 1,
                               "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                               "owned_residual": residual},
        }
        _write(OUTPUT_SOURCE, source)
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_LONG_WINDOW_SOURCE_RECONSTRUCTION_V1_GATE: pass" if passed else "STAGE4F_D_CPP_WORKER_LONG_WINDOW_SOURCE_RECONSTRUCTION_V1_GATE: do_not_pass",
        "status": "pass" if passed else "do_not_pass", "parent_stage": PARENT_STAGE_ID,
        "parent_barrier_checkpoint": str(ACCEPTED_BARRIER_CHECKPOINT),
        "parent_barrier_sha256": ACCEPTED_BARRIER_SHA256, "replayed_steps": len(rows),
        "replayed_step_range": [600, 639], "failure": failure, "owned_residual": residual,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "output_source": str(OUTPUT_SOURCE) if passed else None,
        "output_source_sha256": _sha256(OUTPUT_SOURCE) if passed else None,
        "old_evidence_modified": False, "next_real_segment_started": False,
    }
    _write(DERIVATION_ROOT / "source_reconstruction_gate.json", gate)
    _write(DERIVATION_ROOT / "source_replay_audit.json", {"rows": rows, "failure": failure,
                                                           "source_parent_read_only": str(PARENT_SOURCE)})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
