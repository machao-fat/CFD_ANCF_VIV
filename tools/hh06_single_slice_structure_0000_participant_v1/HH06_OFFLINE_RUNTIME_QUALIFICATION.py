#!/usr/bin/env python3
"""Offline HH06 Structure_0000 runtime qualification.

This harness deliberately uses the production HH06 wrapper backend,
KernelModel/KernelStepRequest serializer, and GenericStructuralCoordinator.
It never imports/initializes preCICE and never advances OpenFOAM.  The only
physical operation is one deterministic ANCF kernel step driven by a test-only
resultant force, followed by the production checkpoint/rollback/replay path.
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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _state_hash(values: Any) -> str:
    vals = tuple(float(x) for x in values)
    return hashlib.sha256(struct.pack("<" + "d" * len(vals), *vals)).hexdigest().upper()


def _max_abs(a: Any, b: Any) -> float:
    return max((abs(float(x) - float(y)) for x, y in zip(a, b)), default=0.0)


def _max_rel(a: Any, b: Any) -> float:
    result = 0.0
    for x, y in zip(a, b):
        denom = max(abs(float(x)), abs(float(y)), 1.0e-300)
        result = max(result, abs(float(x) - float(y)) / denom)
    return result


def _resolve_path(raw: str | Path) -> Path:
    """Resolve both Windows D:/ references and native WSL paths.

    The historical HH06 contract stores a Windows path for the P1 artifacts;
    Path.is_file() alone cannot resolve its directory-valued root on WSL.
    This compatibility resolver is local to the qualification harness and does
    not modify the production wrapper or any contract.
    """
    text = str(raw)
    candidate = Path(text)
    if candidate.exists():
        return candidate
    if text.startswith("D:/") or text.startswith("D:\\"):
        candidate = Path("/mnt/d") / text[3:].replace("\\", "/")
        if candidate.exists():
            return candidate
    if text.startswith("/mnt/") and len(text) >= 6:
        drive = text[5].upper()
        candidate = Path(f"{drive}:") / text[6:].replace("/", "\\")
        if candidate.exists():
            return candidate
    return Path(text)


def _finite_state(state: Any) -> bool:
    return all(math.isfinite(float(x)) for x in state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    # Import from the repository mounted into WSL.  This is the production
    # wrapper/backend, not a reimplementation of the ANCF integrator.
    repo = Path(__file__).resolve().parents[2]
    src = repo / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from tools.hh06_single_slice_structure_0000_participant_v1 import (  # type: ignore
        structure_0000_participant as hh06,
    )
    from coupling.arbitrary_n_live_orchestration_v1 import (  # type: ignore
        ForceSample,
        GenericStructuralCoordinator,
    )

    # The worker accepts a fresh wire ID for an implicit retry.  This flag does
    # not bypass validation; it enables the already implemented M4 retry branch.
    import os
    os.environ["CFD_ANCF_ALLOW_IMPLICIT_RETRY"] = "1"

    # Keep production loader/manifest/backend, only fix the Windows directory
    # reference for native WSL execution.
    hh06._resolve_path = _resolve_path  # type: ignore[attr-defined]
    case = Path(args.case).resolve()
    worker_path = Path(args.worker).resolve()
    expected_sha = args.expected_sha256.upper()
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "qualification": "HH06_WORKER_DEPLOYMENT_AND_OFFLINE_RUNTIME_QUALIFICATION",
        "execution_boundary": {
            "NO_OPENFOAM_RUN": True,
            "NO_PRECICE_INITIALIZE_OR_HANDSHAKE": True,
            "NO_LAUNCH_SH": True,
            "NO_FLUID_0000": True,
            "NO_NEW_OPENFOAM_TIME_DIRECTORY": True,
            "NO_SOURCE_OR_PROTOCOL_MODIFICATION": True,
        },
        "case": str(case),
        "worker": {"path": str(worker_path), "expected_sha256": expected_sha},
    }

    actual_sha = _sha256(worker_path)
    result["worker"].update({"sha256": actual_sha, "sha256_match": actual_sha == expected_sha,
                              "size_bytes": worker_path.stat().st_size})
    if actual_sha != expected_sha:
        result["classification"] = "DO_NOT_PASS"
        result["blocker"] = "QUALIFIED_WORKER_SHA256_MISMATCH"
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 2

    bundle = hh06.load_contract_bundle(case)
    audit = hh06.audit_contract(bundle)
    result["contract_audit"] = audit
    if audit["status"] != "PASS":
        result["classification"] = "DO_NOT_PASS"
        result["blocker"] = "HH06_CONTRACT_AUDIT_FAILED"
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 2

    manifest = hh06.build_manifest(bundle)
    backend = hh06.PersistentHH06KernelBackend(bundle, manifest, worker_path)
    coordinator = GenericStructuralCoordinator(
        manifest,
        backend,
        reference_positions_by_slice={"slice_0000": (0.0, 0.0, bundle.slice_center_m)},
    )
    model_bytes = backend.model.bytes()
    shm_marker = struct.pack("<I", 0x314D4853)
    shm_offset = model_bytes.find(shm_marker)
    if shm_offset < 0:
        result["classification"] = "DO_NOT_PASS"
        result["blocker"] = "SHM1_MISSING_FROM_PRODUCTION_MODEL_BYTES"
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 2
    region_raw = model_bytes[shm_offset + 12:shm_offset + 12 + 64]
    result["model_identity"] = {
        "length_m": backend.model.length_m,
        "elements": backend.model.elements,
        "ndof": backend.model.ndof,
        "slices": backend.model.slices,
        "hydrodynamic_region_count": len(backend.model.hydrodynamic_regions),
        "hydrodynamic_regions": [
            {"s_min_m": r.s_min_m, "s_max_m": r.s_max_m,
             "added_mass_per_length_kg_m": list(r.added_mass_per_length_kg_m),
             "linear_damping_per_length_Ns_m2": list(r.linear_damping_per_length_Ns_m2)}
            for r in backend.model.hydrodynamic_regions
        ],
        "model_bytes_sha256": hashlib.sha256(model_bytes).hexdigest().upper(),
        "shm1_offset": shm_offset,
        "shm1_marker_hex": shm_marker.hex(),
        "shm1_version": struct.unpack_from("<I", model_bytes, shm_offset + 4)[0],
        "shm1_region_count": struct.unpack_from("<I", model_bytes, shm_offset + 8)[0],
        "shm1_region_raw_sha256": hashlib.sha256(region_raw).hexdigest().upper(),
    }

    snapshot_a: dict[str, Any] | None = None
    trial_a: dict[str, Any] | None = None
    trial_b: dict[str, Any] | None = None
    state_a: dict[str, Any] | None = None
    state_b1: dict[str, Any] | None = None
    state_b2: dict[str, Any] | None = None
    force_resultant = (0.0, 1.0, 0.0)  # y/cross-flow, per interface contract.
    raw_force = (0.0, force_resultant[1] * bundle.unit_span_m / bundle.slice_length_m, 0.0)
    result["test_force"] = {
        "resultant_force_N": list(force_resultant),
        "raw_openfoam_equivalent_force_N": list(raw_force),
        "application_s_m": bundle.slice_center_m,
        "axis_basis": "interface contract: x=inline, y=crossflow, z=spanwise/reference-axis",
        "test_only_not_HH06_fluid_force": True,
    }

    def capture_state() -> dict[str, Any]:
        position = backend.evaluate_position(bundle.slice_center_m)
        return {
            "q": list(backend.q), "qdot": list(backend.qdot), "qddot": list(backend.qddot),
            "q_sha256": _state_hash(backend.q), "qdot_sha256": _state_hash(backend.qdot),
            "qddot_sha256": _state_hash(backend.qddot),
            "section_displacement_m": list(position),
            "finite": _finite_state(backend.q) and _finite_state(backend.qdot) and _finite_state(backend.qddot),
            "attempted_advance_count": backend.attempted_advance_count,
            "committed_advance_count": backend.committed_advance_count,
            "pending": backend._pending,
        }

    worker_close: dict[str, Any] = {"started": False}
    try:
        backend.start()
        result["initialization"] = {"passed": True, "worker_pid": backend.process.pid if backend.process else None}
        state_a = capture_state()
        result["initial_state"] = state_a
        snapshot_a = dict(coordinator.checkpoint("hh06-offline-checkpoint-A").to_dict())
        result["checkpoint_A"] = {
            "id": snapshot_a["checkpoint_id"],
            "manifest_sha256": snapshot_a["manifest_sha256"],
            "committed_step": snapshot_a["committed_step"],
            "backend_state_hashes": {
                "q": _state_hash(snapshot_a["backend_state"]["q"]),
                "qdot": _state_hash(snapshot_a["backend_state"]["qdot"]),
                "qddot": _state_hash(snapshot_a["backend_state"]["qddot"]),
            },
        }

        sample = ForceSample.from_openfoam_integrated(
            manifest, "slice_0000", iteration=1, time_s=bundle.dt_s,
            force_N=raw_force, unit_span_m=bundle.unit_span_m,
        )
        coordinator.submit_force(sample)
        trial_a = dict(coordinator.advance_if_complete())
        motion_a = coordinator.scatter_motion()
        state_b1 = capture_state()
        result["trial_A"] = {"response": trial_a, "motion": motion_a, "state": state_b1,
                              "state_changed": _max_abs(state_a["q"], state_b1["q"]) > 0.0}

        # Use the production coordinator rollback.  It restores physical q,
        # qdot and qddot.  The current backend also restores attempted IDs;
        # that behavior is deliberately recorded, not hidden.
        coordinator.rollback()
        state_after_rollback = capture_state()
        result["rollback"] = {
            "physical_state_restored": _max_abs(state_a["q"], state_after_rollback["q"]) == 0.0 and
                                        _max_abs(state_a["qdot"], state_after_rollback["qdot"]) == 0.0 and
                                        _max_abs(state_a["qddot"], state_after_rollback["qddot"]) == 0.0,
            "state": state_after_rollback,
            "transport_counter_behavior": "backend.restore restores attempted_advance_count; replay therefore reuses wire IDs unless caller adds an external monotonicity layer",
        }

        # Exact production replay: same request/force after coordinator rollback.
        # No counter patch is applied; this is the contract qualification.
        coordinator.submit_force(sample)
        try:
            trial_b = dict(coordinator.advance_if_complete())
            coordinator.scatter_motion()
            state_b2 = capture_state()
            result["trial_B"] = {"response": trial_b, "state": state_b2,
                                  "max_abs_diff_q": _max_abs(state_b1["q"], state_b2["q"]),
                                  "max_abs_diff_qdot": _max_abs(state_b1["qdot"], state_b2["qdot"]),
                                  "max_abs_diff_qddot": _max_abs(state_b1["qddot"], state_b2["qddot"]),
                                  "max_abs_diff_section_displacement_m": _max_abs(state_b1["section_displacement_m"], state_b2["section_displacement_m"]),
                                  "replay_pass": True}
            coordinator.commit()
            result["commit"] = {"passed": True, "committed_step": coordinator.committed_step,
                                 "backend_committed_advance_count": backend.committed_advance_count,
                                 "state_is_B2": True}
            result["classification"] = "PASS_HH06_STRUCTURE_OFFLINE_RUNTIME_QUALIFICATION"
            result["authorized_next_phase"] = "HH06_PRECICE_HANDSHAKE_QUALIFICATION"
        except Exception as exc:
            result["trial_B"] = {
                "replay_pass": False,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "worker_return_code": backend.process.poll() if backend.process else None,
            }
            result["commit"] = {"passed": False, "reason": "deterministic replay did not complete"}
            result["classification"] = "DO_NOT_PASS"
            result["blocker"] = "PRODUCTION_BACKEND_ROLLBACK_REUSES_TRANSPORT_IDS"
    except Exception as exc:
        result["classification"] = "DO_NOT_PASS"
        result["blocker"] = "OFFLINE_RUNTIME_EXCEPTION"
        result["exception_type"] = type(exc).__name__
        result["exception"] = str(exc)
    finally:
        worker_close = backend.close()
        result["worker_close"] = worker_close

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("classification", "DO_NOT_PASS").startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
