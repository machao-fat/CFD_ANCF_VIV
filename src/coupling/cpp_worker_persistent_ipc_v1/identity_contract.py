"""Versioned human/runtime identity to fixed-width IPC identity conversion.

The C++ and Python v1 frames reserve a terminating NUL in each fixed-width
identity field.  Human-readable names and filesystem paths are therefore
evidence metadata, never wire identities.
"""
from __future__ import annotations

import hashlib
from typing import Mapping

from .kernel_protocol import ID_CASE, ID_RUN
from .protocol import FrameError


SCHEMA_VERSION = "cfd-ancf-ipc-identity-contract-v1"
MAX_RUN_UTF8_BYTES = ID_RUN - 1
MAX_CASE_UTF8_BYTES = ID_CASE - 1


def _human(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 for char in value):
        raise FrameError(f"{name} is missing or contains a control character")
    return value


def validate_wire_id(value: object, name: str, maximum_bytes: int) -> str:
    """Validate one wire field before a worker is created."""
    text = _human(value, name)
    raw = text.encode("utf-8")
    if b"\0" in raw or len(raw) > maximum_bytes:
        raise FrameError(f"{name} must occupy 1..{maximum_bytes} UTF-8 bytes")
    return text


def _derived(prefix: str, human: str, maximum_bytes: int) -> str:
    # 60 hexadecimal characters give 240 bits while keeping prefix + ID <= 63
    # bytes.  A candidate collision with a distinct human identity is rejected
    # by ``build_identity`` rather than silently changing a persisted ID.
    result = prefix + hashlib.sha256((SCHEMA_VERSION + "\0" + human).encode("utf-8")).hexdigest()[:60]
    return validate_wire_id(result, prefix.rstrip("-"), maximum_bytes)


def build_identity(human_run_name: object, human_case_name: object, runtime_path: object) -> dict[str, object]:
    """Return stable, ASCII wire IDs plus their non-wire provenance.

    Collision handling is intentionally fail-closed: callers persist this
    ledger for the runtime and must reject a short-ID collision instead of
    silently selecting a different identity for an already named run.
    """
    run_name = _human(human_run_name, "human_runtime_name")
    case_name = _human(human_case_name, "human_case_name")
    path = _human(runtime_path, "runtime_path")
    run_id = _derived("r1-", run_name, MAX_RUN_UTF8_BYTES)
    case_id = _derived("c1-", case_name, MAX_CASE_UTF8_BYTES)
    if run_id == case_id:
        raise FrameError("IPC run/case identity collision")
    return {
        "schema_version": SCHEMA_VERSION,
        "human_runtime_name": run_name,
        "human_case_name": case_name,
        "runtime_path": path,
        "run_id": run_id,
        "case_id": case_id,
        "encoding": "UTF-8; derived IDs are ASCII",
        "max_run_id_utf8_bytes": MAX_RUN_UTF8_BYTES,
        "max_case_id_utf8_bytes": MAX_CASE_UTF8_BYTES,
        "derivation": "prefix r1-/c1- plus first 60 lowercase SHA-256 hex characters of schema_version + NUL + full human identity",
        "collision_policy": "fail_closed if a persisted ledger maps a derived ID to a different full human identity",
        "wire_request_id_policy": "monotonic and non-restorable across rollback",
        "physical_window_id_policy": "physical identity is restorable across rollback",
    }


def assert_ledger_compatible(identity: Mapping[str, object], existing: Mapping[str, object] | None = None) -> None:
    """Validate a newly generated ledger and reject a persisted collision."""
    run_id = validate_wire_id(identity.get("run_id"), "run_id", MAX_RUN_UTF8_BYTES)
    case_id = validate_wire_id(identity.get("case_id"), "case_id", MAX_CASE_UTF8_BYTES)
    if existing is None:
        return
    for key, value in (("run_id", run_id), ("case_id", case_id)):
        if existing.get(key) == value and existing.get("human_" + ("runtime_name" if key == "run_id" else "case_name")) != identity.get("human_" + ("runtime_name" if key == "run_id" else "case_name")):
            raise FrameError(f"persisted IPC {key} collision")
