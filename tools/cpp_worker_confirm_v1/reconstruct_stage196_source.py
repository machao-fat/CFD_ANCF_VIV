"""Offline, deterministic reconstruction of the C++ state at Stage196 step599.

This replays the already committed Stage196 applied-force journal through a
fresh C++ worker only. It never starts MATLAB, OpenFOAM, WSL, or CFD and never
modifies Stage196 artifacts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as base
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker, _fixture
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest

STAGE_ID = "stage4f_d_cpp_worker_continuation_source_reconstruction_v1"
RUN_ID = "cpp_worker_continuation_replay_001"
CASE_ID = "cpp_worker_continuation_replay_case_001"
PARENT_STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v12"
PARENT_RUN_ID = "cpp_worker_persistent_ipc_confirm_012"
PARENT_RESULTS = PROJECT / "results/196_cpp_worker_persistent_ipc_confirm_v12"
REPLAY_RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/continuation_replay_001"
RESULTS = PROJECT / "results/197_cpp_worker_continuation_source_reconstruction_v1"
SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
OUTPUT_SOURCE = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/continuation_source_step00000599_v1.json"


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_state(state: dict[str, list[float]]) -> None:
    if set(state) != {"q", "qdot", "qddot"}:
        raise RuntimeError("replayed state schema is incomplete")
    lengths = {len(state[key]) for key in state}
    if len(lengths) != 1 or not lengths or any(not math.isfinite(float(v)) for values in state.values() for v in values):
        raise RuntimeError("replayed state is non-finite or dimensionally inconsistent")


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def main() -> int:
    if RESULTS.exists() or REPLAY_RUNTIME.exists():
        raise RuntimeError("reconstruction destinations already exist; refusing retry")
    if not SOURCE.is_file() or not PARENT_RESULTS.is_dir():
        raise RuntimeError("protected source or Stage196 results are missing")
    parent_gate = json.loads((PARENT_RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json").read_text(encoding="utf-8"))
    if parent_gate.get("gate") != "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: pass":
        raise RuntimeError("parent Stage196 Gate is not pass")
    summary = json.loads((PARENT_RESULTS / "confirm_summary.json").read_text(encoding="utf-8"))
    records = summary.get("records")
    if not isinstance(records, list) or len(records) != 40:
        raise RuntimeError("Stage196 committed record count is not exactly 40")
    records = sorted(records, key=lambda row: int(row.get("global_step", -1)))
    if [int(row["global_step"]) for row in records] != list(range(560, 600)):
        raise RuntimeError("Stage196 record sequence is not 560..599")

    model, _q, _qdot, _qddot, base_load = _fixture()
    model = base.normalize_model(model)
    mass_matrix = base._source_mass_matrix()
    worker = KernelWorker(
        base.WORKER_EXE, REPLAY_RUNTIME / "process", RUN_ID, CASE_ID,
        expected_model_contract_sha256=base.EXPECTED_MODEL_CONTRACT_SHA256,
    )
    adapter = CppKernelCampaignAdapter.from_checkpoint(
        worker=worker, model=model, request_factory=KernelStepRequest,
        checkpoint=SOURCE, expected_sha256=base.SOURCE_SHA256,
        run_id=RUN_ID, case_id=CASE_ID, dt_s=0.00125, base_load=base_load,
        slice_count=3, mass_matrix=mass_matrix,
        expected_model_contract_sha256=base.EXPECTED_MODEL_CONTRACT_SHA256,
    )
    rows: list[dict[str, object]] = []
    failure: str | None = None
    state: dict[str, list[float]] | None = None
    try:
        REPLAY_RUNTIME.mkdir(parents=True, exist_ok=True)
        adapter.start()
        for row in records:
            step = int(row["global_step"])
            time_s = float(row["time_s"])
            metadata = row.get("checkpoint_metadata")
            if not isinstance(metadata, dict):
                raise RuntimeError(f"step {step} has no checkpoint metadata")
            applied = metadata.get("applied_slice_forces_N")
            if not isinstance(applied, list) or len(applied) != 3:
                raise RuntimeError(f"step {step} applied force journal is incomplete")
            force = tuple(tuple(float(v) for v in values) for values in applied)
            prediction, _ = adapter.predict(step, time_s, force)
            correction, _ = adapter.correct(step, time_s, force)
            adapter.finalize_committed()
            state = adapter.state_view()
            finite_state(state)
            rows.append({"step": step, "time_s": time_s, "tick": 2_207_500_000 + (step - 559) * 1_250_000,
                         "prediction_payload_hash": prediction["payload_hash"],
                         "correction_payload_hash": correction["payload_hash"],
                         "finite_value_audit": True, "state_sha256": hashlib.sha256(canonical(state)).hexdigest()})
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            adapter.stop()
        except Exception as exc:
            failure = failure or f"cleanup failed: {exc}"

    residual = int(getattr(adapter, "owned_residual", 0))
    if failure is None and state is not None:
        finite_state(state)
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        last_metadata = records[-1]["checkpoint_metadata"]
        source = {
            "schema_version": "stage100_cpp_continuation_source_v1",
            "status": "committed", "step": 599, "time_s": 2.2575, "time_tick": 2_257_500_000,
            "structure": state,
            "applied_slice_forces_N": last_metadata["applied_slice_forces_N"],
            "next_applied_slice_forces_N": last_metadata["next_applied_slice_forces_N"],
            "parent": {"stage_id": PARENT_STAGE_ID, "run_id": PARENT_RUN_ID,
                       "result_gate": str(PARENT_RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json"),
                       "parent_checkpoint_step": 599},
            "source_parent_sha256": base.SOURCE_SHA256,
            "reconstruction": {"stage_id": STAGE_ID, "run_id": RUN_ID, "replayed_steps": "560..599",
                               "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                               "replay_worker_startup": 1, "owned_residual": residual},
        }
        write(OUTPUT_SOURCE, source)
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_CONTINUATION_SOURCE_RECONSTRUCTION_V1_GATE: pass" if failure is None and residual == 0 and len(rows) == 40 else "STAGE4F_D_CPP_WORKER_CONTINUATION_SOURCE_RECONSTRUCTION_V1_GATE: do_not_pass",
        "status": "pass" if failure is None and residual == 0 and len(rows) == 40 else "do_not_pass",
        "parent_stage": PARENT_STAGE_ID, "parent_run_id": PARENT_RUN_ID,
        "parent_source_step": 599, "replayed_step_range": [560, 599],
        "replayed_steps": len(rows), "failure": failure, "owned_residual": residual,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "output_source": str(OUTPUT_SOURCE) if failure is None else None,
        "output_source_sha256": sha256(OUTPUT_SOURCE) if failure is None else None,
        "old_evidence_modified": False, "old_runtime_reused": False,
        "next_real_segment_started": False,
    }
    write(RESULTS / "continuation_source_reconstruction_gate.json", gate)
    write(RESULTS / "replay_audit.json", {"stage_id": STAGE_ID, "rows": rows, "failure": failure,
                                           "parent_results_read_only": str(PARENT_RESULTS),
                                           "real_process_starts": gate["real_process_starts"],
                                           "owned_residual": residual})
    (RESULTS / "report.md").write_text(
        "# C++ continuation source reconstruction\n\n"
        f"Gate: `{gate['gate']}`\n\n"
        "Stage196 was replayed offline through a fresh C++ worker using its committed applied-force journal. "
        "No MATLAB, OpenFOAM, WSL, or CFD process was started. The generated step599 source is eligible for a new "
        "step600--639 bounded segment only when this Gate passes.\n",
        encoding="utf-8")
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
