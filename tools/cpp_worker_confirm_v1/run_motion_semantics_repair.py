"""Offline audit for the C++/MATLAB prediction-state semantic repair."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker, _fixture
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest


PROJECT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT / "results/125_cpp_worker_motion_semantics_repair_v1"
RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/offline_motion_semantics_repair_001"
WORKER_EXE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
SOURCE_SHA = "341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226"


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(values: list[float]) -> bool:
    return bool(values) and all(math.isfinite(float(item)) for item in values)


def main() -> int:
    if RESULTS.exists() or RUNTIME.exists():
        raise RuntimeError("offline repair destinations must be fresh")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if sha256(SOURCE) != SOURCE_SHA or source.get("step") != 559:
        raise RuntimeError("accepted source checkpoint audit failed")
    model, _q, _qdot, _qddot, base_load = _fixture()
    structure = source["structure"]
    worker = KernelWorker(WORKER_EXE, RUNTIME / "process", "offline_motion_semantics_repair_001", "offline_motion_semantics_case_001")
    adapter = CppKernelCampaignAdapter(worker=worker, model=model, request_factory=KernelStepRequest,
        run_id="offline_motion_semantics_repair_001", case_id="offline_motion_semantics_case_001",
        source_global_step=559, source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
        q=structure["q"], qdot=structure["qdot"], qddot=structure["qddot"],
        base_load=base_load, slice_count=3)
    rows = []
    started = time.perf_counter()
    previous = tuple(tuple(float(value) for value in source["previous_slice_forces_N"][sid]) for sid in range(3))
    try:
        adapter.start()
        for bridge in range(1, 41):
            step = 559 + bridge
            time_s = 2.2075 + bridge * 0.00125
            prediction, _ = adapter.predict(step, time_s, previous)
            state = {"q": prediction["predictor"], "qdot": prediction["predictor_qdot"], "qddot": prediction["predictor_qddot"]}
            if any(not finite(state[key]) for key in state):
                raise RuntimeError(f"non-finite complete prediction state at step {step}")
            correction, _ = adapter.correct(step, time_s, ((0.0, 0.0, 0.0),) * 3)
            adapter.finalize_committed()
            rows.append({"global_step": step, "case_local_bridge_step": bridge, "time_s": time_s,
                         "integer_tick": 2_207_500_000 + bridge * 1_250_000,
                         "motion_state_hash": hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                         "max_abs_q": max(abs(float(v)) for v in state["q"]),
                         "max_abs_qdot": max(abs(float(v)) for v in state["qdot"]),
                         "max_abs_qddot": max(abs(float(v)) for v in state["qddot"]),
                         "correction_ack": correction["ack"], "finite_value_audit": True})
            previous = ((0.0, 0.0, 0.0),) * 3
    finally:
        adapter.shutdown()
    result = {"stage_id": "stage4f_d_cpp_worker_motion_semantics_repair_v1",
              "run_id": "offline_motion_semantics_repair_001", "case_id": "offline_motion_semantics_case_001",
              "status": "pass" if len(rows) == 40 and adapter.owned_residual == 0 else "do_not_pass",
              "semantic_contract": "MATLAB ancf_advance_step prediction exposes complete q/qd/qdd state",
              "adapter_motion_source": "C++ response q/qdot/qddot from one previous-force advance",
              "explicit_newmark_predictor_not_used_for_motion": True,
              "requested_steps": 40, "processed_steps": len(rows), "rows": rows,
              "worker_startup": adapter.start_count, "owned_residual": adapter.owned_residual,
              "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
              "old_evidence_modified": False, "old_runtime_reused": False,
              "physical_parameters_modified": False, "global_dt_modified": False,
              "numerical_thresholds_modified": False, "wall_clock_s": time.perf_counter() - started}
    write(RESULTS / "motion_semantics_repair_audit.json", result)
    gate = {"gate": "STAGE4F_D_CPP_WORKER_MOTION_SEMANTICS_REPAIR_V1_GATE: pass" if result["status"] == "pass" else "STAGE4F_D_CPP_WORKER_MOTION_SEMANTICS_REPAIR_V1_GATE: do_not_pass",
            "status": result["status"], "processed_steps": len(rows), "worker_startup": adapter.start_count,
            "owned_residual": adapter.owned_residual, "real_process_starts": result["real_process_starts"],
            "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed", "new_real_confirm_authorization_required": True}
    write(RESULTS / "stage4f_d_cpp_worker_motion_semantics_repair_v1_gate.json", gate)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
