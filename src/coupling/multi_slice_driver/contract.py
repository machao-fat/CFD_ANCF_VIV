"""B-side filesystem helpers for the frozen 0.2.1 A-module contract.

The schema, canonical JSON, hashes, records, markers and validators are not
defined here.  They are imported from ``multi_slice_mapping.mapping`` so the
orchestrator cannot silently drift from the production protocol.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import (
    CONSUMED_FIELDS,
    IDENTITY_R_GL,
    LOAD_FIELDS,
    MOTION_FIELDS,
    READY_FIELDS,
    SCHEMA_VERSION,
    ConsumedMarker,
    HashValidationError,
    IdentityError,
    LoadRecord,
    MotionRecord,
    RuntimeConfig,
    SchemaError,
    SliceDefinition,
    SliceManifest,
    atomic_write_csv,
    atomic_write_json,
    build_H_for_manifest,
    canonical_json_bytes,
    create_consumed_marker,
    create_ready_marker,
    map_integrated_slice_forces,
    read_load_csv,
    read_motion_csv,
    sha256_file,
    sha256_json,
    validate_load_record,
    validate_motion_record,
    validate_record_transaction,
)


ContractError = SchemaError


class SliceSpec(SliceDefinition):
    """Compatibility constructor backed by the A-module data class.

    ``unit_span_m`` defaults only for old test call sites.  No validation or
    hashing is duplicated here.
    """

    def __init__(self, slice_id: int, s_ref_m: float, slice_length_m: float, unit_span_m: float = 1.0) -> None:
        super().__init__(slice_id, s_ref_m, slice_length_m, unit_span_m)


def validate_specs(specs: Sequence[SliceDefinition]) -> tuple[SliceDefinition, ...]:
    ordered = tuple(sorted(specs, key=lambda item: item.slice_id))
    expected = tuple(range(len(ordered)))
    actual = tuple(item.slice_id for item in ordered)
    if actual != expected or len(set(actual)) != len(actual):
        raise IdentityError(f"slice_id set must be exactly 0..N-1, got {actual}")
    return ordered


def build_slice_manifest(
    case_id: str,
    specs: Sequence[SliceDefinition],
    *,
    reference_length_m: float | None = None,
    represented_length_m: float | None = None,
    R_GL: Sequence[Sequence[float]] = IDENTITY_R_GL,
) -> dict[str, object]:
    ordered = validate_specs(specs)
    represented = float(represented_length_m if represented_length_m is not None else sum(item.slice_length_m for item in ordered))
    inferred_reference = max(
        represented,
        max(item.s_ref_m for item in ordered) if ordered else 0.0,
    )
    reference = float(reference_length_m if reference_length_m is not None else inferred_reference)
    manifest = SliceManifest(
        schema_version=SCHEMA_VERSION,
        case_id=case_id,
        reference_length_m=reference,
        represented_length_m=represented,
        R_GL=R_GL,
        slices=tuple(ordered),
    )
    return manifest.to_dict()


def build_config(
    *,
    case_id: str,
    dt_s: float,
    timeout_s: float,
    specs: Sequence[SliceDefinition] | None = None,
    slice_manifest_sha256: str | None = None,
    start_time_s: float = 0.0,
    reference_length_m: float | None = None,
    represented_length_m: float | None = None,
    R_GL: Sequence[Sequence[float]] = IDENTITY_R_GL,
) -> dict[str, object]:
    if slice_manifest_sha256 is None:
        if specs is None:
            raise ContractError("specs or slice_manifest_sha256 is required")
        manifest = SliceManifest.from_mapping(build_slice_manifest(
            case_id, specs, reference_length_m=reference_length_m,
            represented_length_m=represented_length_m, R_GL=R_GL,
        ))
        slice_manifest_sha256 = manifest.slice_manifest_sha256
    config = RuntimeConfig(
        schema_version=SCHEMA_VERSION,
        case_id=case_id,
        dt_s=dt_s,
        timeout_s=timeout_s,
        start_time_s=start_time_s,
        coupling_iteration=0,
        coupling_scheme="explicit_weak",
        slice_manifest_sha256=slice_manifest_sha256,
    )
    return config.to_dict()


def read_single_csv(path: str | Path, fields: Sequence[str]) -> dict[str, str]:
    target = Path(path)
    if not target.is_file():
        raise ContractError(f"missing payload: {target}")
    with target.open("r", newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        actual = list(reader.fieldnames or [])
        missing = [field for field in fields if field not in actual]
        if missing:
            raise ContractError(f"{target}: missing fields: {', '.join(missing)}")
        rows = list(reader)
    if len(rows) != 1:
        raise ContractError(f"{target}: row_count must be 1")
    return rows[0]


def read_json_object(path: str | Path, *, context: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{context}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{context}: JSON must be an object")
    return value


@dataclass(frozen=True)
class SliceExchangePaths:
    """Immutable per-slice path layout; payload names never overwrite steps."""

    exchange_root: Path
    spec: SliceDefinition

    @property
    def slice_dir(self) -> Path:
        return self.exchange_root / f"slice_{self.spec.slice_id:04d}"

    def payload(self, kind: str, step: int, coupling_iteration: int = 0) -> Path:
        prefix = "motion" if kind == "motion" else "load"
        return self.slice_dir / kind / f"{prefix}_step{step:08d}_iter{coupling_iteration:04d}.csv"

    def ready(self, kind: str, step: int, coupling_iteration: int = 0) -> Path:
        prefix = "motion" if kind == "motion" else "load"
        return self.slice_dir / kind / f"{prefix}_step{step:08d}_iter{coupling_iteration:04d}.ready.json"

    def consumed(self, kind: str, step: int, coupling_iteration: int = 0) -> Path:
        prefix = "motion" if kind == "motion" else "load"
        return self.slice_dir / "consumed" / f"{prefix}_step{step:08d}_iter{coupling_iteration:04d}.consumed.json"

    def ensure(self) -> None:
        for directory in (self.slice_dir / "motion", self.slice_dir / "load", self.slice_dir / "consumed"):
            directory.mkdir(parents=True, exist_ok=True)


__all__ = [
    "CONSUMED_FIELDS", "IDENTITY_R_GL", "LOAD_FIELDS", "MOTION_FIELDS", "READY_FIELDS",
    "SCHEMA_VERSION", "ContractError", "HashValidationError", "IdentityError",
    "LoadRecord", "MotionRecord", "RuntimeConfig", "SliceDefinition", "SliceManifest",
    "SliceSpec", "SliceExchangePaths", "atomic_write_csv", "atomic_write_json",
    "build_H_for_manifest", "build_config", "build_slice_manifest", "canonical_json_bytes",
    "create_consumed_marker", "create_ready_marker", "map_integrated_slice_forces",
    "read_json_object", "read_load_csv", "read_motion_csv", "read_single_csv", "sha256_file",
    "sha256_json", "validate_load_record", "validate_motion_record", "validate_record_transaction",
]
