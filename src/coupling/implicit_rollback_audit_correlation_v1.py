"""Fail-closed correlation of OpenFOAM rollback diagnostics by generation.

Adapter ``window_id`` is an observability counter, not a globally unique
checkpoint identity.  The trace order defines checkpoint generations; a
restore is valid only against the latest preceding generation and only when
its physical time/timeIndex and required state identities agree.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isclose
from typing import Any


CHECKPOINT = "CHECKPOINT_WRITE"
RESTORE = "POST_ROLLBACK_BEFORE_NEXT_INPUT"
REQUIRED_HASH_STATES = (
    "U", "p", "phi", "Uf", "pointDisplacement", "cellDisplacement",
    "mesh_points", "old_points",
)


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    row: Mapping[str, Any]


def _as_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} is not an integer")
    return value


def _as_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} is not numeric")
    return float(value)


def _ordered_events(trace: Sequence[Mapping[str, Any]]) -> list[TraceEvent]:
    ordered: list[TraceEvent] = []
    seen: set[int] = set()
    previous = 0
    for ordinal, row in enumerate(trace, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"trace row {ordinal} is not an object")
        sequence = _as_int(row.get("event_sequence", ordinal), "event_sequence")
        if sequence in seen or sequence <= previous:
            raise ValueError("trace event sequence is ambiguous or non-monotonic")
        seen.add(sequence)
        previous = sequence
        ordered.append(TraceEvent(sequence, row))
    return ordered


def _state(row: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    states = row.get("states")
    if not isinstance(states, Mapping):
        raise ValueError("trace row has no state inventory")
    state = states.get(name)
    if not isinstance(state, Mapping):
        raise ValueError(f"trace state {name} is absent")
    return state


def _hash(state: Mapping[str, Any], name: str) -> str:
    value = state.get("canonical_hash_fnv1a64")
    if not isinstance(value, str) or not value:
        raise ValueError(f"state {name} has no canonical hash")
    return value


def _old_time_equivalent(checkpoint: Mapping[str, Any], restored: Mapping[str, Any], name: str) -> dict[str, object]:
    before = _as_int(checkpoint.get("old_time_levels", 0), f"{name}.checkpoint.old_time_levels")
    after = _as_int(restored.get("old_time_levels", 0), f"{name}.restore.old_time_levels")
    if before == after:
        if before == 0:
            return {"status": "NOT_APPLICABLE_NO_HISTORY", "pass": True}
        return {"status": "PERSISTENT_RESTORED",
                "pass": checkpoint.get("old_time_canonical_hash_fnv1a64") == restored.get("old_time_canonical_hash_fnv1a64")}
    # OF10 may lazily create a first oldTime object during a trial. It is
    # acceptable only when the reconstructed history equals the checkpoint's
    # current field, never a trial value.
    if before == 0 and after == 1:
        return {"status": "RECONSTRUCTED_FROM_CHECKPOINT_CURRENT",
                "pass": restored.get("old_time_canonical_hash_fnv1a64") == _hash(checkpoint, name)}
    return {"status": "HISTORY_LEVEL_MISMATCH", "pass": False}


def _mesh_phi_equivalent(checkpoint: Mapping[str, Any], restored: Mapping[str, Any]) -> dict[str, object]:
    before = _state(checkpoint, "meshPhi")
    after = _state(restored, "meshPhi")
    before_class = before.get("classification")
    after_class = after.get("classification")
    if before_class == "NOT_OBSERVABLE_NOT_REGISTERED" and after_class == "PERSISTENT_RESTORED":
        # The frozen OF10 contract permits registry-safe derived creation. The
        # post-restore object must nevertheless be finite and fingerprintable.
        return {"status": "RECONSTRUCTED_CONSISTENT", "pass": bool(after.get("finite")) and isinstance(after.get("canonical_hash_fnv1a64"), str)}
    if before_class == "PERSISTENT_RESTORED" and after_class == "PERSISTENT_RESTORED":
        return {"status": "PERSISTENT_RESTORED", "pass": _hash(before, "meshPhi") == _hash(after, "meshPhi")}
    return {"status": "UNSUPPORTED_MESHPHI_LIFECYCLE", "pass": False}


def _compare_generation(checkpoint: TraceEvent, restored: TraceEvent, generation: int) -> dict[str, object]:
    cp, rs = checkpoint.row, restored.row
    try:
        cp_time = _as_float(cp.get("physical_time"), "checkpoint.physical_time")
        rs_time = _as_float(rs.get("physical_time"), "restore.physical_time")
        time_identity = isclose(cp_time, rs_time, rel_tol=0.0, abs_tol=1.0e-12) and \
            _as_int(cp.get("time_index"), "checkpoint.time_index") == _as_int(rs.get("time_index"), "restore.time_index")
        build_identity = cp.get("adapter_build_sha256") == rs.get("adapter_build_sha256")
        fields: dict[str, bool] = {}
        for name in REQUIRED_HASH_STATES:
            fields[name] = _hash(_state(cp, name), name) == _hash(_state(rs, name), name)
        histories = {name: _old_time_equivalent(_state(cp, name), _state(rs, name), name)
                     for name in ("U", "p", "phi", "Uf", "pointDisplacement", "cellDisplacement")}
        mesh_phi = _mesh_phi_equivalent(cp, rs)
        field_identity = all(fields[name] for name in ("U", "p", "phi", "Uf", "pointDisplacement", "cellDisplacement")) and \
            all(bool(item["pass"]) for item in histories.values()) and bool(mesh_phi["pass"])
        mesh_identity = fields["mesh_points"] and fields["old_points"]
        return {
            "generation": generation,
            "checkpoint_event_sequence": checkpoint.sequence,
            "restore_event_sequence": restored.sequence,
            "checkpoint_adapter_window_id": cp.get("window_id"),
            "restore_adapter_window_id": rs.get("window_id"),
            "physical_time": {"checkpoint": cp_time, "restore": rs_time},
            "time_index": {"checkpoint": cp.get("time_index"), "restore": rs.get("time_index")},
            "time_identity": time_identity,
            "adapter_build_identity": build_identity,
            "state_hash_identity": fields,
            "old_time": histories,
            "meshPhi": mesh_phi,
            "field_history_identity": field_identity,
            "mesh_identity": mesh_identity,
            "pass": time_identity and build_identity and field_identity and mesh_identity,
        }
    except ValueError as error:
        return {"generation": generation, "checkpoint_event_sequence": checkpoint.sequence,
                "restore_event_sequence": restored.sequence, "pass": False,
                "error": str(error)}


def correlate_rollback_trace(trace: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Pair each restore with exactly one active checkpoint generation."""
    try:
        events = _ordered_events(trace)
    except ValueError as error:
        return {"status": "FAIL", "error": str(error), "generations": [], "restore_pairs": []}
    active: TraceEvent | None = None
    generations: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    errors: list[str] = []
    for event in events:
        kind = event.row.get("event")
        if kind == CHECKPOINT:
            active = event
            generations.append({"generation": len(generations) + 1, "event_sequence": event.sequence,
                                "adapter_window_id": event.row.get("window_id"),
                                "physical_time": event.row.get("physical_time"), "time_index": event.row.get("time_index")})
        elif kind == RESTORE:
            if active is None:
                errors.append(f"restore event {event.sequence} has no preceding active checkpoint")
                continue
            pair = _compare_generation(active, event, len(generations))
            pairs.append(pair)
            if not pair.get("pass"):
                errors.append(f"checkpoint generation {len(generations)} does not restore identically")
    if not generations:
        errors.append("no checkpoint generation observed")
    if not pairs:
        errors.append("no rollback restore observed")
    return {"status": "PASS" if not errors else "FAIL", "generations": generations,
            "restore_pairs": pairs, "errors": errors,
            "generation_contract": "latest chronologically preceding CHECKPOINT_WRITE; exact physical time/timeIndex and required state identity"}
