"""Fail-fast, atomic motion/load file handshake.

The CSV itself is the payload.  A ready marker is a small JSON document that
binds the payload to a step, physical time, row count and SHA-256 digest.  A
consumer never accepts an unmarked or stale payload and never falls back to a
previous load.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Iterable, Mapping

from ..file_exchange.csv_contract import (
    ContractError,
    validate_load_csv,
    validate_motion_csv,
)


class FileCouplingError(RuntimeError):
    """Raised when the handshake is missing, stale or inconsistent."""


def _finite_time(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise FileCouplingError("time_s must be finite")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(dict(payload), stream, ensure_ascii=True, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.replace(temporary_path, path)
                break
            except PermissionError:
                # OpenFOAM may be between two short marker reads on DrvFs.
                # Retry the atomic commit; never expose the temporary file as
                # a ready marker and never fall back to the old step.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_payload(
    payload_path: Path,
    kind: str,
    expected_s_ref_m: Iterable[float] | None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    expected_s_ref = list(expected_s_ref_m) if expected_s_ref_m is not None else None
    try:
        if kind == "motion":
            rows = validate_motion_csv(payload_path, expected_s_ref_m=expected_s_ref)
        elif kind == "load":
            expected_ids = list(range(len(expected_s_ref))) if expected_s_ref is not None else (0,)
            rows = validate_load_csv(
                payload_path,
                expected_slice_ids=expected_ids,
                expected_s_ref_m=expected_s_ref,
            )
        else:
            raise FileCouplingError(f"unknown payload kind: {kind}")
    except ContractError as exc:
        raise FileCouplingError(str(exc)) from exc

    first = rows[0]
    try:
        step = int(float(first["step"]))
        coupling_iteration = int(float(first["coupling_iteration"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise FileCouplingError(f"{payload_path}: invalid step metadata") from exc
    time_s = _finite_time(float(first["time_s"]))
    if step < 0 or coupling_iteration < 0:
        raise FileCouplingError(f"{payload_path}: step and coupling_iteration must be non-negative")
    return rows, {
        "schema_version": str(first["schema_version"]),
        "step": step,
        "coupling_iteration": coupling_iteration,
        "time_s": time_s,
        "row_count": len(rows),
        "sha256": _sha256(payload_path),
        "kind": kind,
        "payload": payload_path.name,
    }


def publish_ready(
    payload_path: str | Path,
    marker_path: str | Path,
    *,
    kind: str,
    expected_s_ref_m: Iterable[float] | None = None,
) -> dict[str, object]:
    """Validate a complete payload and atomically publish its ready marker."""

    payload = Path(payload_path)
    marker = Path(marker_path)
    if not payload.is_file():
        raise FileCouplingError(f"missing payload: {payload}")
    _, metadata = _validate_payload(payload, kind, expected_s_ref_m)
    _atomic_json(marker, metadata)
    return metadata


def _read_marker(marker_path: Path) -> dict[str, object]:
    if not marker_path.is_file():
        raise FileCouplingError(f"missing ready marker: {marker_path}")
    try:
        with marker_path.open("r", encoding="utf-8") as stream:
            marker = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise FileCouplingError(f"invalid ready marker: {marker_path}") from exc
    if not isinstance(marker, dict):
        raise FileCouplingError(f"ready marker is not a JSON object: {marker_path}")
    return marker


def read_ready_snapshot(
    payload_path: str | Path,
    marker_path: str | Path,
    *,
    kind: str,
    expected_step: int,
    expected_time_s: float,
    expected_coupling_iteration: int | None = None,
    expected_s_ref_m: Iterable[float] | None = None,
    time_tolerance_s: float = 1.0e-12,
) -> list[dict[str, str]]:
    """Read one ready payload and enforce exact step/time/digest agreement."""

    payload = Path(payload_path)
    marker = _read_marker(Path(marker_path))
    rows, metadata = _validate_payload(payload, kind, expected_s_ref_m)
    required = ("kind", "step", "coupling_iteration", "time_s", "row_count", "sha256", "payload")
    missing = [key for key in required if key not in marker]
    if missing:
        raise FileCouplingError(f"ready marker missing fields: {', '.join(missing)}")
    if marker["kind"] != kind or marker["payload"] != payload.name:
        raise FileCouplingError("ready marker does not identify the requested payload")
    if int(marker["step"]) != int(expected_step) or metadata["step"] != int(expected_step):
        raise FileCouplingError(
            f"step mismatch: expected {expected_step}, marker {marker['step']}, payload {metadata['step']}"
        )
    marker_iteration = int(marker["coupling_iteration"])
    payload_iteration = int(metadata["coupling_iteration"])
    if marker_iteration != payload_iteration:
        raise FileCouplingError("coupling_iteration mismatch between marker and payload")
    if expected_coupling_iteration is not None:
        expected_iteration = int(expected_coupling_iteration)
        if marker_iteration != expected_iteration:
            raise FileCouplingError(
                f"coupling_iteration mismatch: expected {expected_iteration}, got {marker_iteration}"
            )
    expected_time_s = _finite_time(expected_time_s)
    marker_time = _finite_time(float(marker["time_s"]))
    payload_time = float(metadata["time_s"])
    if max(abs(marker_time - expected_time_s), abs(payload_time - expected_time_s)) > time_tolerance_s * max(1.0, abs(expected_time_s)):
        raise FileCouplingError("time_s mismatch between handshake and requested step")
    if int(marker["row_count"]) != metadata["row_count"] or marker["sha256"] != metadata["sha256"]:
        raise FileCouplingError("payload changed after ready marker was published")
    return rows


def wait_for_ready(
    payload_path: str | Path,
    marker_path: str | Path,
    *,
    kind: str,
    expected_step: int,
    expected_time_s: float,
    expected_coupling_iteration: int | None = None,
    expected_s_ref_m: Iterable[float] | None = None,
    timeout_s: float = 30.0,
    poll_s: float = 0.01,
) -> list[dict[str, str]]:
    """Wait for one marker, then validate it; stale markers fail immediately."""

    deadline = time.monotonic() + float(timeout_s)
    last_error: FileCouplingError | None = None
    while time.monotonic() <= deadline:
        try:
            return read_ready_snapshot(
                payload_path,
                marker_path,
                kind=kind,
                expected_step=expected_step,
                expected_time_s=expected_time_s,
                expected_coupling_iteration=expected_coupling_iteration,
                expected_s_ref_m=expected_s_ref_m,
            )
        except FileCouplingError as exc:
            last_error = exc
            if "step mismatch" in str(exc) or "time_s mismatch" in str(exc) or "coupling_iteration mismatch" in str(exc):
                raise
            time.sleep(max(0.0, poll_s))
    raise FileCouplingError(f"timeout waiting for {kind} ready: {last_error}")
