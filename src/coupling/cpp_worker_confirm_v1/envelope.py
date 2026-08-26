"""Stage-local identity envelopes around the protected 0.2.1 payloads.

The legacy motion/load records remain byte-for-byte their established schema.
This envelope is an additional scheduler-side audit object: it binds a record
hash to the run, bridge identity and upstream C++ transaction before the
adapter crosses into the legacy OpenFOAM bridge.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from coupling.multi_slice_mapping.mapping import MotionRecord, SCHEMA_VERSION as FORMAL_SCHEMA_VERSION
from coupling.performance_optimization_v2.coordinator import CoordinatorError, StepIdentity

SCHEMA_VERSION = "stage100_cpp_coupling_envelope_v1"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def payload_hash(value: Mapping[str, Any]) -> str:
    try:
        return hashlib.sha256(_canonical(value)).hexdigest()
    except (TypeError, ValueError, OverflowError) as exc:
        raise CoordinatorError("coupling envelope payload is not canonical JSON") from exc


@dataclass(frozen=True)
class MotionEnvelope:
    identity: StepIdentity
    slice_id: int
    motion: MotionRecord
    upstream_request_id: int
    upstream_transaction_id: int
    upstream_sequence: int
    payload_sha256: str
    producer: str = "cpp_ancf_worker"
    consumer: str = "openfoam_slice_adapter"
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def create(cls, *, identity: StepIdentity, motion: MotionRecord,
               upstream_request_id: int, upstream_transaction_id: int,
               upstream_sequence: int) -> "MotionEnvelope":
        if (motion.slice_id < 0 or motion.case_id != identity.case_id or
                motion.step != identity.global_step or
                not math.isclose(motion.time_s, identity.time_s, rel_tol=0.0, abs_tol=1e-12)):
            raise CoordinatorError("motion envelope identity mismatch")
        for name, value in (("upstream_request_id", upstream_request_id),
                            ("upstream_transaction_id", upstream_transaction_id),
                            ("upstream_sequence", upstream_sequence)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise CoordinatorError(f"motion envelope {name} is invalid")
        return cls(identity=identity, slice_id=motion.slice_id, motion=motion,
                   upstream_request_id=upstream_request_id,
                   upstream_transaction_id=upstream_transaction_id,
                   upstream_sequence=upstream_sequence,
                   payload_sha256=payload_hash(motion.to_dict()))

    def validate(self, *, identity: StepIdentity, slice_id: int) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CoordinatorError("motion envelope schema mismatch")
        if self.producer != "cpp_ancf_worker" or self.consumer != "openfoam_slice_adapter":
            raise CoordinatorError("motion envelope endpoint mismatch")
        if self.identity != identity or self.slice_id != slice_id or self.motion.slice_id != slice_id:
            raise CoordinatorError("motion envelope identity mismatch")
        if self.payload_sha256 != payload_hash(self.motion.to_dict()):
            raise CoordinatorError("motion envelope payload hash mismatch")

    def audit_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "producer": self.producer,
            "consumer": self.consumer, "run_id": self.identity.run_id,
            "case_id": self.identity.case_id, "global_step": self.identity.global_step,
            "case_local_bridge_step": self.identity.case_local_bridge_step,
            "time_s": self.identity.time_s, "integer_tick": self.identity.integer_tick,
            "request_id": self.identity.request_id, "transaction_id": self.identity.transaction_id,
            "slice_id": self.slice_id, "upstream_request_id": self.upstream_request_id,
            "upstream_transaction_id": self.upstream_transaction_id,
            "upstream_sequence": self.upstream_sequence,
            "payload_sha256": self.payload_sha256,
        }


def load_envelope(*, identity: StepIdentity, slice_id: int, load: Mapping[str, Any],
                  motion: MotionEnvelope) -> dict[str, Any]:
    motion.validate(identity=identity, slice_id=slice_id)
    if not isinstance(load, Mapping):
        raise CoordinatorError("load envelope payload must be a mapping")
    # LoadRecord is validated by the adapter before this helper is called, but
    # keep this public envelope boundary independently fail-closed.  This
    # prevents a caller from binding a valid motion envelope to a stale load.
    if (load.get("schema_version") != FORMAL_SCHEMA_VERSION or
            load.get("case_id") != identity.case_id or
            load.get("step") != identity.global_step or
            load.get("slice_id") != slice_id or
            load.get("coupling_iteration") != 0):
        raise CoordinatorError("load envelope identity mismatch")
    try:
        load_time = float(load["time_s"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CoordinatorError("load envelope time is invalid") from exc
    if not math.isfinite(load_time) or not math.isclose(load_time, identity.time_s, rel_tol=0.0, abs_tol=1e-12):
        raise CoordinatorError("load envelope time mismatch")
    digest = payload_hash(load)
    return {
        "schema_version": SCHEMA_VERSION, "producer": "openfoam_slice_adapter",
        "consumer": "cpp_ancf_scheduler", "run_id": identity.run_id,
        "case_id": identity.case_id, "global_step": identity.global_step,
        "case_local_bridge_step": identity.case_local_bridge_step,
        "time_s": identity.time_s, "integer_tick": identity.integer_tick,
        "request_id": identity.request_id, "transaction_id": identity.transaction_id,
        "slice_id": slice_id, "motion_payload_sha256": motion.payload_sha256,
        "payload_sha256": digest, "ack": 1,
    }


__all__ = ["MotionEnvelope", "SCHEMA_VERSION", "load_envelope", "payload_hash"]
