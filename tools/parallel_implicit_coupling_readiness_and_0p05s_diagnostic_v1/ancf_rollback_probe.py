"""Real C++ ANCF checkpoint/rollback qualification; never launches CFD."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest


def model_from_contract(contract: dict[str, object]):
    source = ROOT / "tools" / "three_slice_force_contract_smoke_v1" / "structure_participant.py"
    spec = importlib.util.spec_from_file_location("implicit_rollback_structure_participant", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen structure-participant model builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.model_from_contract(contract)


RUN_ID = "parallel_implicit_ancf_rollback_probe_v1_run_004"
CASE_ID = "parallel_implicit_ancf_rollback_probe_v1_case_004"
DT = 0.005
LOADS = ((22503.305595427, 0.0, 0.0),) * 3


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def main() -> int:
    runtime = ROOT / "runtime" / RUN_ID
    if runtime.exists():
        raise RuntimeError(f"refusing to overwrite runtime: {runtime}")
    runtime.mkdir(parents=True)
    contract_path = ROOT / "tools" / "preconditioned_coupled_0p1s_smoke_v1" / "preconditioned_coupled_0p1s_smoke_v1_contract.json"
    state_path = ROOT / "runtime" / "stage4f_d_cpp_worker_initialization_v1" / "run_20260827_cpp_only" / "ancf_t0_state_cpp.json"
    worker_path = ROOT / "runtime" / "parallel_implicit_coupling_readiness_and_0p05s_diagnostic_v1" / "cpp_worker_build" / "cfd_ancf_ancf_kernel_worker"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    model = model_from_contract(contract)
    q, qdot, qddot = (tuple(float(x) for x in state[key]) for key in ("q", "qdot", "qddot"))
    mass = tuple(float(x) for x in state["mass_matrix"])
    base = tuple(float(x) for x in state["base_load"])
    model_hash = hashlib.sha256(model.bytes() + struct.pack("<" + "d" * len(mass), *mass)).hexdigest()
    worker = KernelWorker(worker_path, runtime / "cpp_worker", RUN_ID, CASE_ID,
                          expected_model_contract_sha256=model_hash, allow_implicit_retry=True)
    adapter = CppKernelCampaignAdapter(
        worker=worker, model=model, request_factory=KernelStepRequest,
        run_id=RUN_ID, case_id=CASE_ID, source_global_step=0, source_time_s=0.0,
        source_tick=0, dt_s=DT, q=q, qdot=qdot, qddot=qddot, base_load=base,
        mass_matrix=mass, strict_numerical_contract=True,
        expected_model_contract_sha256=model_hash, implicit_rollback_transport=True,
    )
    checkpoint = runtime / "window_000000_checkpoint.json"
    trials: list[dict[str, object]] = []
    error: str | None = None
    try:
        adapter.start()
        adapter.save_checkpoint(checkpoint)
        initial = adapter.state_view()
        for attempt in range(1, 7):
            prediction, _ = adapter.predict(1, DT, ((0.0, 0.0, 0.0),) * 3)
            correction, _ = adapter.correct(1, DT, LOADS)
            trial_state = adapter.state_view()
            trials.append({
                "attempt": attempt,
                "prediction": prediction,
                "correction": correction,
                "state_sha256": sha(trial_state),
                "state": trial_state,
            })
            adapter.load_checkpoint(checkpoint)
            restored = adapter.state_view()
            if restored != initial:
                raise RuntimeError("restored ANCF state is not bitwise-identical to checkpoint")
        reference = trials[0]
        if any(item["state"] != reference["state"] for item in trials[1:]):
            raise RuntimeError("identical post-rollback trials are not deterministic")
    except Exception as exc:  # Record the first failure before termination.
        error = f"{type(exc).__name__}: {exc}"
    finally:
        adapter.shutdown()
    output = {
        "schema_version": "ancf-rollback-probe-v1",
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "dt_s": DT,
        "load_N_per_slice": [list(row) for row in LOADS],
        "checkpoint_schema": CppKernelCampaignAdapter.CHECKPOINT_SCHEMA,
        "wire_identity_policy": "monotonic_attempt_identity; physical window step/tick restored independently",
        "attempted_trials": 6,
        "completed_trials": len(trials),
        "ANCF_ROLLBACK": "PASS" if error is None and len(trials) == 6 else "FAIL",
        "error": error,
        "trials": trials,
        "worker_audit": worker.audit,
        "owned_residual": adapter.owned_residual,
        "real_cfd_process_starts": 0,
    }
    (runtime / "ancf_rollback_probe.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("ANCF_ROLLBACK", "completed_trials", "error", "owned_residual")}, ensure_ascii=False))
    return 0 if output["ANCF_ROLLBACK"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
