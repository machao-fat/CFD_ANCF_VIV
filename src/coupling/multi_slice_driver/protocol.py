"""0.2.1 ready/consumed transactions backed by A-module validators."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from .contract import (
    CONSUMED_FIELDS,
    LOAD_FIELDS,
    MOTION_FIELDS,
    READY_FIELDS,
    ContractError,
    LoadRecord,
    MotionRecord,
    RuntimeConfig,
    SliceDefinition,
    SliceExchangePaths,
    SliceManifest,
    atomic_write_csv,
    atomic_write_json,
    create_consumed_marker,
    create_ready_marker,
    read_json_object,
    read_load_csv,
    read_motion_csv,
)
from ..multi_slice_mapping.mapping import ConsumedMarker, ReadyMarker


class ProtocolError(RuntimeError):
    """Raised when one 0.2.1 transaction cannot be verified."""


# V3 may tune polling without changing the 0.2.1 message or validation
# contract.  The coordinator restores this process-local setting on exit.
POLL_INTERVAL_S = 0.005


def _record(kind: str, value: Mapping[str, Any] | MotionRecord | LoadRecord, manifest: SliceManifest) -> MotionRecord | LoadRecord:
    if kind == "motion":
        return value if isinstance(value, MotionRecord) else MotionRecord.from_mapping(value)
    if kind == "load":
        return value if isinstance(value, LoadRecord) else LoadRecord.from_mapping(value, manifest.R_GL)
    raise ProtocolError(f"unsupported payload kind: {kind}")


def publish_payload(
    *,
    payload_path: str | Path,
    ready_path: str | Path,
    kind: str,
    record: Mapping[str, Any] | MotionRecord | LoadRecord,
    manifest: SliceManifest,
    runtime_config: RuntimeConfig,
) -> dict[str, object]:
    """Write payload, fsync/replace it, and publish ready last."""

    try:
        parsed = _record(kind, record, manifest)
        if kind == "motion":
            fields = MOTION_FIELDS
        else:
            fields = LOAD_FIELDS
        atomic_write_csv(payload_path, fields, parsed.to_dict())
        marker = create_ready_marker(
            payload_path, parsed, manifest, runtime_config, payload_kind=kind,
        )
        atomic_write_json(ready_path, marker.to_dict())
        return marker.to_dict()
    except Exception as exc:
        raise ProtocolError(f"cannot publish {kind} for slice {getattr(record, 'slice_id', '?')}: {exc}") from exc


def _wait_ready(
    *,
    paths: SliceExchangePaths,
    kind: str,
    step: int,
    time_s: float,
    manifest: SliceManifest,
    runtime_config: RuntimeConfig,
    timeout_s: float,
) -> tuple[dict[str, object], MotionRecord | LoadRecord]:
    if timeout_s <= 0.0:
        raise ProtocolError("timeout_s must be strictly > 0")
    deadline = time.monotonic() + timeout_s
    marker_path = paths.ready(kind, step)
    payload_path = paths.payload(kind, step)
    last_error = "marker not present"
    while time.monotonic() <= deadline:
        if marker_path.is_file():
            try:
                raw = read_json_object(marker_path, context=str(marker_path))
                marker = ReadyMarker.from_mapping(raw)
                marker.validate_against(
                    manifest, runtime_config, expected_step=step,
                    expected_time_s=time_s, payload_path=payload_path,
                )
                if kind == "motion":
                    parsed = read_motion_csv(
                        payload_path, manifest, expected_step=step,
                        expected_time_s=time_s, runtime_config=runtime_config,
                        ready_marker=marker,
                    )
                else:
                    parsed = read_load_csv(
                        payload_path, manifest, expected_step=step,
                        expected_time_s=time_s, runtime_config=runtime_config,
                        ready_marker=marker,
                    )
                return marker.to_dict(), parsed
            except Exception as exc:
                last_error = str(exc)
                raise ProtocolError(last_error) from exc
        time.sleep(POLL_INTERVAL_S)
    raise ProtocolError(f"timeout waiting for ready {kind}: {last_error}")


def wait_ready(
    *, paths: SliceExchangePaths, kind: str, step: int, time_s: float,
    manifest: SliceManifest, runtime_config: RuntimeConfig, timeout_s: float,
) -> dict[str, object]:
    return _wait_ready(
        paths=paths, kind=kind, step=step, time_s=time_s,
        manifest=manifest, runtime_config=runtime_config, timeout_s=timeout_s,
    )[0]


def read_ready_payload(
    *, paths: SliceExchangePaths, kind: str, step: int, time_s: float,
    manifest: SliceManifest, runtime_config: RuntimeConfig, timeout_s: float,
) -> MotionRecord | LoadRecord:
    return _wait_ready(
        paths=paths, kind=kind, step=step, time_s=time_s,
        manifest=manifest, runtime_config=runtime_config, timeout_s=timeout_s,
    )[1]


def publish_consumed(
    *, paths: SliceExchangePaths, kind: str, step: int, time_s: float,
    manifest: SliceManifest, runtime_config: RuntimeConfig, consumer: str,
) -> dict[str, object]:
    ready, _ = _wait_ready(
        paths=paths, kind=kind, step=step, time_s=time_s,
        manifest=manifest, runtime_config=runtime_config,
        timeout_s=max(0.001, runtime_config.timeout_s),
    )
    marker = ReadyMarker.from_mapping(ready)
    consumed = create_consumed_marker(
        marker, manifest, runtime_config, consumer,
        payload_path=paths.payload(kind, step),
    )
    atomic_write_json(paths.consumed(kind, step), consumed.to_dict())
    return consumed.to_dict()


def wait_consumed(
    *, paths: SliceExchangePaths, kind: str, step: int, time_s: float,
    manifest: SliceManifest, runtime_config: RuntimeConfig, timeout_s: float,
) -> dict[str, object]:
    ready, _ = _wait_ready(
        paths=paths, kind=kind, step=step, time_s=time_s,
        manifest=manifest, runtime_config=runtime_config, timeout_s=timeout_s,
    )
    payload_path = paths.payload(kind, step)
    ready_marker = ReadyMarker.from_mapping(ready)
    marker_path = paths.consumed(kind, step)
    deadline = time.monotonic() + timeout_s
    last_error = "marker not present"
    while time.monotonic() <= deadline:
        if marker_path.is_file():
            try:
                marker = ConsumedMarker.from_mapping(read_json_object(marker_path, context=str(marker_path)))
                marker.validate_against(
                    manifest, runtime_config, expected_step=step,
                    expected_time_s=time_s, payload_path=payload_path,
                )
                if marker.payload_sha256 != ready_marker.payload_sha256 or marker.payload_kind != kind:
                    raise ProtocolError("consumed marker disagrees with ready marker")
                return marker.to_dict()
            except Exception as exc:
                last_error = str(exc)
                raise ProtocolError(last_error) from exc
        time.sleep(POLL_INTERVAL_S)
    raise ProtocolError(f"timeout waiting for consumed {kind}: {last_error}")
