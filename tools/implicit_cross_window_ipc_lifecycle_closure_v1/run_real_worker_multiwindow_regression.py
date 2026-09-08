"""Real C++ worker cross-window IPC regression; deliberately no CFD/preCICE."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARTICIPANT = load_module(
    ROOT / "tools" / "checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1"
    / "implicit_structure_participant.py", "implicit_structure_participant_cross_window")
LOAD_A = ((22503.305595427, 0.0, 0.0),) * 3
LOAD_B = ((11251.6527977135, 0.0, 0.0),) * 3


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def model_inputs():
    contract = json.loads((ROOT / "tools" / "preconditioned_coupled_0p1s_smoke_v1"
                           / "preconditioned_coupled_0p1s_smoke_v1_contract.json").read_text(encoding="utf-8"))
    state = json.loads((ROOT / "runtime" / "stage4f_d_cpp_worker_initialization_v1"
                        / "run_20260827_cpp_only" / "ancf_t0_state_cpp.json").read_text(encoding="utf-8"))
    model = PARTICIPANT.model_from_contract(contract)
    q, qdot, qddot = (tuple(float(value) for value in state[name])
                       for name in ("q", "qdot", "qddot"))
    mass = tuple(float(value) for value in state["mass_matrix"])
    base = tuple(float(value) for value in state["base_load"])
    model_hash = hashlib.sha256(model.bytes() + struct.pack("<" + "d" * len(mass), *mass)).hexdigest()
    return model, q, qdot, qddot, mass, base, model_hash


def state_snapshot(adapter: CppKernelCampaignAdapter) -> dict[str, object]:
    state = adapter.state_view()
    return {"state": state, "sha256": canonical_hash(state)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--explicit-regression", action="store_true",
                        help="exercise the unchanged non-rollback production transport")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if runtime.exists():
        raise RuntimeError(f"refusing to overwrite immutable runtime {runtime}")
    runtime.mkdir(parents=True)
    run_id = "implicit_cross_window_ipc_v1"
    model, q, qdot, qddot, mass, base, model_hash = model_inputs()
    worker = KernelWorker(args.worker.resolve(), runtime / "cpp_worker", run_id,
                          "cross_window_real_worker", expected_model_contract_sha256=model_hash,
                          allow_implicit_retry=not args.explicit_regression)
    adapter = CppKernelCampaignAdapter(
        worker=worker, model=model, request_factory=KernelStepRequest, run_id=run_id,
        case_id="cross_window_real_worker", source_global_step=0, source_time_s=0.0,
        source_tick=0, dt_s=0.005, q=q, qdot=qdot, qddot=qddot,
        base_load=base, mass_matrix=mass, strict_numerical_contract=True,
        expected_model_contract_sha256=model_hash,
        implicit_rollback_transport=not args.explicit_regression)
    events: list[dict[str, object]] = []
    windows: list[dict[str, object]] = []
    result: dict[str, object]
    previous = [(0.0, 0.0, 0.0)] * 3
    try:
        adapter.start()
        for window in range(1, 4):
            target_time = window * 0.005
            checkpoint = runtime / "checkpoints" / f"window_{window:06d}.json"
            adapter.save_checkpoint(checkpoint)
            checkpoint_state = state_snapshot(adapter)
            discarded: list[dict[str, object]] = []
            # Three same-input trials force restore/retry while retaining fresh
            # wire identities. Their physical results must be deterministic.
            # Explicit transport uses the same three real committed windows but
            # cannot and must not request rollback retries.
            for trial in range(1, 4 if not args.explicit_regression else 1):
                prediction, _ = adapter.predict(window, target_time, previous)
                correction, _ = adapter.correct(window, target_time, LOAD_A)
                trial_state = state_snapshot(adapter)
                discarded.append({"trial": trial, "prediction": prediction,
                                  "correction": correction, "state": trial_state})
                events.append({"event": "discarded_trial", "window": window, "trial": trial,
                               "prediction_wire": prediction["wire_sequence"],
                               "correction_wire": correction["wire_sequence"],
                               "request_ids": [prediction["request_id"], correction["request_id"]],
                               "transaction_ids": [prediction["transaction_id"], correction["transaction_id"]],
                               "physical_state_sha256": trial_state["sha256"]})
                adapter.load_checkpoint(checkpoint)
                restored = state_snapshot(adapter)
                if restored != checkpoint_state:
                    raise RuntimeError(f"window {window} physical restore mismatch")
                events.append({"event": "rollback", "window": window, "trial": trial,
                               "checkpoint_state_sha256": checkpoint_state["sha256"],
                               "post_restore_state_sha256": restored["sha256"]})
            if discarded and len({trial["state"]["sha256"] for trial in discarded}) != 1:
                raise RuntimeError(f"window {window} same-input trial was non-deterministic")
            # A different accepted force must advance from the restored window
            # state, not from any discarded trial state.
            prediction, _ = adapter.predict(window, target_time, previous)
            correction, _ = adapter.correct(window, target_time, LOAD_B)
            accepted_state = state_snapshot(adapter)
            if accepted_state == checkpoint_state:
                raise RuntimeError(f"window {window} accepted trial did not advance state")
            if discarded and accepted_state["sha256"] == discarded[0]["state"]["sha256"]:
                raise RuntimeError(f"window {window} different-input trial leaked discarded state")
            adapter.finalize_committed()
            committed = state_snapshot(adapter)
            if committed != accepted_state:
                raise RuntimeError(f"window {window} commit changed accepted state")
            wire_ids = [wire for entry in discarded for wire in
                        (entry["prediction"]["wire_sequence"], entry["correction"]["wire_sequence"])] + \
                       [prediction["wire_sequence"], correction["wire_sequence"]]
            windows.append({"window": window, "target_time_s": target_time,
                            "checkpoint_state": checkpoint_state, "discarded": discarded,
                            "accepted": {"prediction": prediction, "correction": correction,
                                         "state": accepted_state}, "committed_state": committed,
                            "wire_ids": wire_ids, "previous_force_before": previous,
                            "previous_force_after": LOAD_B})
            events.append({"event": "window_commit", "window": window,
                           "committed_state_sha256": committed["sha256"],
                           "last_wire": correction["wire_sequence"],
                           "committed_time_s": target_time})
            previous = [tuple(row) for row in LOAD_B]
        all_wires = [wire for item in windows for wire in item["wire_ids"]]
        if all_wires != list(range(1, len(all_wires) + 1)):
            raise RuntimeError(f"wire IDs are not globally contiguous/unique: {all_wires}")
        result = {"CROSS_WINDOW_IPC_LIFECYCLE": "PASS", "real_cpp_worker": True,
                  "transport_mode": "parallel-explicit" if args.explicit_regression else "parallel-implicit",
                  "windows_committed": 3, "rollbacks": 0 if args.explicit_regression else 9,
                  "same_input_deterministic": "NOT_APPLICABLE_EXPLICIT" if args.explicit_regression else True,
                  "different_input_isolated": "NOT_APPLICABLE_EXPLICIT" if args.explicit_regression else True,
                  "physical_state_only_commits": True, "wire_ids": all_wires,
                  "windows": windows, "events": events}
    except Exception as error:
        result = {"CROSS_WINDOW_IPC_LIFECYCLE": "FAIL", "real_cpp_worker": True,
                  "transport_mode": "parallel-explicit" if args.explicit_regression else "parallel-implicit",
                  "error": f"{type(error).__name__}: {error}", "windows": windows,
                  "events": events}
    finally:
        adapter.shutdown()
    result["worker_audit"] = worker.audit
    result["worker_sha256"] = hashlib.sha256(args.worker.read_bytes()).hexdigest()
    (runtime / "real_worker_multiwindow_regression.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result.get(key) for key in
                      ("CROSS_WINDOW_IPC_LIFECYCLE", "windows_committed", "rollbacks", "error")},
                     ensure_ascii=False))
    return 0 if result["CROSS_WINDOW_IPC_LIFECYCLE"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
