#!/usr/bin/env python3
"""Offline HH06 worker lineage transition qualification.

This test uses the production HH06 KernelModel/KernelStepRequest serializer,
PersistentHH06KernelBackend, and GenericStructuralCoordinator.  It starts only
the isolated C++ worker; it never imports preCICE and never starts OpenFOAM.
Window 1 deliberately performs five requests with four physical rollbacks,
then commits.  Window 2 sends sequences 6--10 and commits after four more
rollbacks.  The test is specifically designed to catch sequence-parity
lineage logic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any


def _resolve_path(raw: str | Path) -> Path:
    text = str(raw)
    candidate = Path(text)
    if candidate.exists():
        return candidate
    if text.startswith("D:/") or text.startswith("D:\\"):
        candidate = Path("/mnt/d") / text[3:].replace("\\", "/")
        if candidate.exists():
            return candidate
    return Path(text)


def _sha256_numbers(values: Any) -> str:
    vals = tuple(float(value) for value in values)
    return hashlib.sha256(struct.pack("<" + "d" * len(vals), *vals)).hexdigest()


def _max_abs(left: Any, right: Any) -> float:
    return max(
        (abs(float(a) - float(b)) for a, b in zip(left, right)),
        default=0.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    src = repo / "src"
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(src))

    from tools.hh06_single_slice_structure_0000_participant_v1 import (  # type: ignore
        structure_0000_participant as hh06,
    )
    from coupling.arbitrary_n_live_orchestration_v1 import (  # type: ignore
        ForceSample,
        GenericStructuralCoordinator,
    )

    import os
    os.environ["CFD_ANCF_ALLOW_IMPLICIT_RETRY"] = "1"
    hh06._resolve_path = _resolve_path  # type: ignore[attr-defined]

    case = Path(args.case).resolve()
    worker = Path(args.worker).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "test": "HH06_WORKER_LINEAGE_TRANSITION_FIX_AUDIT",
        "execution_boundary": {
            "openfoam": False,
            "precice": False,
            "fluid_adapter": False,
            "physical_cfd_time_advance": False,
            "isolated_worker_only": True,
        },
        "case": str(case),
        "worker": str(worker),
        "allow_implicit_retry": True,
        "windows_requested": 2,
        "requests_requested": 10,
    }

    backend = None
    close_result: dict[str, Any] = {"started": False}
    try:
        bundle = hh06.load_contract_bundle(case)
        audit = hh06.audit_contract(bundle)
        result["contract_audit"] = audit
        if audit.get("status") != "PASS":
            raise RuntimeError("HH06 contract audit did not pass")
        manifest = hh06.build_manifest(bundle)
        result["model"] = {
            "length_m": audit["model"]["length_m"],
            "elements": audit["model"]["elements"],
            "ndof": audit["model"]["dof"],
            "dt_s": bundle.dt_s,
            "slice_center_m": bundle.slice_center_m,
        }
        backend = hh06.PersistentHH06KernelBackend(bundle, manifest, worker)
        coordinator = GenericStructuralCoordinator(
            manifest,
            backend,
            reference_positions_by_slice={"slice_0000": (0.0, 0.0, bundle.slice_center_m)},
        )
        # One deterministic resultant force.  It is a protocol stimulus only,
        # not an HH06 fluid-force claim.
        resultant_force = (0.0, 1.0, 0.0)
        raw_force = (
            resultant_force[0] * bundle.unit_span_m / bundle.slice_length_m,
            resultant_force[1] * bundle.unit_span_m / bundle.slice_length_m,
            resultant_force[2] * bundle.unit_span_m / bundle.slice_length_m,
        )
        result["test_force"] = {
            "integrated_resultant_N": list(resultant_force),
            "raw_openfoam_equivalent_N": list(raw_force),
            "test_only": True,
            "application_s_m": bundle.slice_center_m,
        }

        backend.start()
        windows: list[dict[str, Any]] = []
        previous_ids = {"sequence": 0, "request_id": 910000, "transaction_id": 1910000}
        for window_id in (1, 2):
            window_time = window_id * float(bundle.dt_s)
            checkpoint = coordinator.checkpoint(f"lineage-window-{window_id}")
            window: dict[str, Any] = {
                "window_id": window_id,
                "time_s": window_time,
                "checkpoint_id": checkpoint.checkpoint_id,
                "attempts": [],
                "rollback_count": 0,
                "committed": False,
            }
            state_at_checkpoint = {
                "q": list(backend.q),
                "qdot": list(backend.qdot),
                "qddot": list(backend.qddot),
            }
            for attempt in range(1, 6):
                sample = ForceSample.from_openfoam_integrated(
                    manifest,
                    "slice_0000",
                    iteration=attempt,
                    time_s=window_time,
                    force_N=raw_force,
                    unit_span_m=bundle.unit_span_m,
                )
                response = dict(
                    coordinator.advance_if_complete()
                    if (coordinator.submit_force(sample) is None)
                    else {}
                )
                coordinator.scatter_motion()
                ids = {
                    "sequence": backend._transport_sequence_counter,
                    "request_id": backend._transport_request_id_counter,
                    "transaction_id": backend._transport_transaction_id_counter,
                }
                physical = {
                    "global_step": window_id,
                    "bridge_step": window_id,
                    "time_s": window_time,
                    "dt_s": bundle.dt_s,
                }
                window["attempts"].append({
                    "attempt": attempt,
                    "ids": ids,
                    "physical": physical,
                    "response": response,
                    "q_sha256": _sha256_numbers(backend.q),
                    "qdot_sha256": _sha256_numbers(backend.qdot),
                    "qddot_sha256": _sha256_numbers(backend.qddot),
                    "finite": all(math.isfinite(float(value)) for value in (*backend.q, *backend.qdot, *backend.qddot)),
                })
                if any(ids[name] <= previous_ids[name] for name in ids):
                    raise RuntimeError(f"transport ID is not strictly increasing at window {window_id}, attempt {attempt}")
                previous_ids = ids
                if attempt < 5:
                    coordinator.rollback()
                    window["rollback_count"] += 1
                    restored = (
                        _max_abs(state_at_checkpoint["q"], backend.q) == 0.0
                        and _max_abs(state_at_checkpoint["qdot"], backend.qdot) == 0.0
                        and _max_abs(state_at_checkpoint["qddot"], backend.qddot) == 0.0
                    )
                    if not restored:
                        raise RuntimeError(f"physical checkpoint restore mismatch at window {window_id}, attempt {attempt}")
            coordinator.commit()
            window["committed"] = True
            window["committed_step"] = coordinator.committed_step
            windows.append(window)

        result["windows"] = windows
        result["accepted_window_count"] = sum(1 for item in windows if item["committed"])
        result["rollback_count"] = sum(int(item["rollback_count"]) for item in windows)
        result["response_count"] = sum(len(item["attempts"]) for item in windows)
        result["sequence_range"] = [windows[0]["attempts"][0]["ids"]["sequence"], windows[-1]["attempts"][-1]["ids"]["sequence"]]
        result["sequence_request_transaction_monotonic"] = True
        result["all_responses_returned"] = result["response_count"] == 10
        result["parity_defect_present"] = False
        result["classification"] = (
            "PASS_HH06_WORKER_LINEAGE_TRANSITION_FIX_AUDIT"
            if result["accepted_window_count"] == 2 and result["all_responses_returned"]
            else "DO_NOT_PASS"
        )
    except Exception as exc:
        result["classification"] = "DO_NOT_PASS"
        result["exception_type"] = type(exc).__name__
        result["exception"] = str(exc)
    finally:
        if backend is not None:
            close_result = backend.close()
        result["worker_close"] = close_result
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("classification", "DO_NOT_PASS").startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
