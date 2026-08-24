#!/usr/bin/env python3
"""Validated, atomic CSV exchange for one CFD/ANCF slice snapshot."""

from __future__ import annotations

import csv
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Iterable, Mapping


MOTION_REQUIRED = (
    "schema_version",
    "step",
    "coupling_iteration",
    "time_s",
    "slice_id",
    "s_ref_m",
    "x_m",
    "y_m",
    "z_m",
    "vx_mps",
    "vy_mps",
    "vz_mps",
    "ax_mps2",
    "ay_mps2",
    "az_mps2",
)

LOAD_REQUIRED = (
    "schema_version",
    "step",
    "coupling_iteration",
    "time_s",
    "slice_id",
    "s_ref_m",
    "force_x_N",
    "force_y_N",
    "force_z_N",
)


class ContractError(ValueError):
    """Raised when a file violates the stage-two exchange contract."""


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise ContractError(f"missing CSV: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise ContractError(f"CSV has no header: {path}")
    if not rows:
        raise ContractError(f"CSV has no data rows: {path}")
    return fields, rows


def _require(fields: Iterable[str], required: Iterable[str], path: Path) -> None:
    missing = sorted(set(required).difference(fields))
    if missing:
        raise ContractError(f"{path}: missing columns {', '.join(missing)}")


def _float(row: Mapping[str, str], key: str, path: Path, line: int) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError(f"{path}:{line}: {key} is not numeric") from exc
    if not math.isfinite(value):
        raise ContractError(f"{path}:{line}: {key} is NaN/Inf")
    return value


def validate_motion_csv(
    path: str | Path,
    *,
    expected_s_ref_m: Iterable[float] | None = None,
) -> list[dict[str, str]]:
    """Validate one ANCF motion snapshot and return its rows."""

    path = Path(path)
    fields, rows = _read_rows(path)
    _require(fields, MOTION_REQUIRED, path)
    expected_ids = list(range(len(rows)))
    ids = []
    metadata = []
    s_values = []
    for line, row in enumerate(rows, start=2):
        try:
            sid = int(float(row["slice_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"{path}:{line}: slice_id is not an integer") from exc
        ids.append(sid)
        metadata.append(
            (
                row["schema_version"],
                int(float(row["step"])),
                int(float(row["coupling_iteration"])),
                _float(row, "time_s", path, line),
            )
        )
        s_values.append(_float(row, "s_ref_m", path, line))
        for key in MOTION_REQUIRED[6:]:
            _float(row, key, path, line)
    if ids != expected_ids:
        raise ContractError(f"{path}: slice_id must be contiguous and ordered from 0")
    if len(set(metadata)) != 1:
        raise ContractError(f"{path}: step/time/coupling metadata must be constant")
    if expected_s_ref_m is not None:
        expected = list(expected_s_ref_m)
        if len(expected) != len(s_values) or any(
            abs(a - b) > 1e-10 * max(1.0, abs(b))
            for a, b in zip(s_values, expected)
        ):
            raise ContractError(f"{path}: s_ref_m does not match the structure case")
    return rows


def validate_load_csv(
    path: str | Path,
    *,
    expected_slice_ids: Iterable[int] = (0,),
    expected_s_ref_m: Iterable[float] | None = None,
) -> list[dict[str, str]]:
    """Validate a time history with one or more complete slice rows per time."""

    path = Path(path)
    fields, rows = _read_rows(path)
    _require(fields, LOAD_REQUIRED, path)
    expected = list(expected_slice_ids)
    expected_s_ref = list(expected_s_ref_m) if expected_s_ref_m is not None else None
    if expected_s_ref is not None and len(expected_s_ref) != len(expected):
        raise ContractError(f"{path}: expected_s_ref_m and expected_slice_ids have different lengths")
    by_time: dict[float, list[dict[str, str]]] = {}
    time_order: list[float] = []
    for line, row in enumerate(rows, start=2):
        time = _float(row, "time_s", path, line)
        by_time.setdefault(time, []).append(row)
        if not time_order or time != time_order[-1]:
            time_order.append(time)
        try:
            sid = int(float(row["slice_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"{path}:{line}: slice_id is not an integer") from exc
        if sid not in expected:
            raise ContractError(f"{path}:{line}: unexpected slice_id {sid}")
        if expected_s_ref is not None:
            actual_s_ref = _float(row, "s_ref_m", path, line)
            expected_value = expected_s_ref[expected.index(sid)]
            if abs(actual_s_ref - expected_value) > 1.0e-10 * max(1.0, abs(expected_value)):
                raise ContractError(f"{path}:{line}: s_ref_m does not match the structure case")
        for key in ("step", "coupling_iteration"):
            _float(row, key, path, line)
        for key in fields:
            if key in ("schema_version", "force_representation", "status"):
                continue
            _float(row, key, path, line)
    if len(time_order) > 1 and any(b <= a for a, b in zip(time_order, time_order[1:])):
        raise ContractError(f"{path}: time_s is not strictly increasing")
    for time, group in by_time.items():
        ids = sorted(int(float(row["slice_id"])) for row in group)
        if ids != expected:
            raise ContractError(f"{path}: incomplete slice set at time {time}")
    return rows


def atomic_write_csv(path: str | Path, fieldnames: Iterable[str], rows: Iterable[Mapping[str, object]]) -> None:
    """Write a complete CSV and atomically replace the destination."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        with temporary_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(fieldnames))
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        # On Windows/DrvFs a short-lived reader (for example a progress
        # monitor or antivirus scanner) can temporarily deny the replace even
        # though both files are on the same volume.  Keep atomic semantics but
        # tolerate that transient sharing violation for a bounded interval.
        for attempt in range(101):
            try:
                os.replace(temporary_path, path)
                break
            except PermissionError:
                if attempt == 100:
                    raise
                time.sleep(0.05)
    finally:
        for attempt in range(21):
            try:
                temporary_path.unlink(missing_ok=True)
                break
            except PermissionError:
                if attempt == 20:
                    raise
                time.sleep(0.05)
