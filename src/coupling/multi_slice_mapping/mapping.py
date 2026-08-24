"""Pure-Python Stage-4A multi-slice protocol and mapping primitives.

The module deliberately uses the standard library only.  It keeps the three
force levels explicit:

``OpenFOAM total force [N] -> unit-span force [N/m] -> integrated slice force [N]``.

The integrated force is the only force accepted by the H-transpose mapping.
No ``slice_length_m`` factor is applied in the mapping routine.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
from bisect import bisect_right
from dataclasses import dataclass, is_dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union


SCHEMA_VERSION = "0.2.1"
LEGACY_SCHEMA_VERSIONS = ("0.1.0", "0.2.0")
DEFAULT_TOLERANCE = 1.0e-12
S_REF_TOLERANCE = 1.0e-10
TIME_TOLERANCE = 1.0e-12
GEOMETRY_TOLERANCE = 1.0e-12
FORCE_TOLERANCE = 1.0e-13
VIRTUAL_WORK_TOLERANCE = 1.0e-12

# Explicitly opt-in, process-local fast publication for ephemeral exchange
# files.  Formal checkpoints and restart manifests are never covered unless a
# caller accidentally supplies their exact directory (the coordinator only
# supplies ``cases`` and ``exchange`` roots).
_EPHEMERAL_ATOMIC_ROOTS: tuple[Path, ...] = ()


def set_ephemeral_atomic_roots(roots: Sequence[str | Path]) -> tuple[Path, ...]:
    """Set exchange roots and return the previous value for restoration."""
    global _EPHEMERAL_ATOMIC_ROOTS
    previous = _EPHEMERAL_ATOMIC_ROOTS
    _EPHEMERAL_ATOMIC_ROOTS = tuple(Path(root).resolve() for root in roots)
    return previous


def _ephemeral_atomic_path(path: str | Path) -> bool:
    candidate = Path(path).resolve()
    for root in _EPHEMERAL_ATOMIC_ROOTS:
        try:
            if os.path.commonpath([str(candidate), str(root)]) == str(root):
                return True
        except ValueError:
            continue
    return False

MOTION_FIELDS = (
    "schema_version", "case_id", "step", "coupling_iteration", "time_s",
    "slice_id", "s_ref_m", "slice_length_m", "x_ref_m", "y_ref_m", "z_ref_m",
    "ux_m", "uy_m", "uz_m", "x_m", "y_m", "z_m", "vx_mps", "vy_mps",
    "vz_mps", "ax_mps2", "ay_mps2", "az_mps2", "status",
)

LOAD_FIELDS = (
    "schema_version", "case_id", "step", "coupling_iteration", "time_s",
    "slice_id", "s_ref_m", "slice_length_m", "unit_span_m", "force_representation",
    "openfoam_force_x_N", "openfoam_force_y_N", "openfoam_force_z_N",
    "force_2d_x_Npm", "force_2d_y_Npm", "force_2d_z_Npm", "force_x_N", "force_y_N",
    "force_z_N", "force_local_streamwise_N", "force_local_crossflow_N",
    "force_local_axial_N", "cfd_time_step_s", "status",
)

READY_FIELDS = (
    "schema_version", "marker_type", "payload_kind", "case_id", "slice_id", "step",
    "coupling_iteration", "time_s", "payload", "row_count", "payload_sha256",
    "config_sha256", "slice_manifest_sha256",
)

CONSUMED_FIELDS = (
    "schema_version", "marker_type", "payload_kind", "case_id", "slice_id", "step",
    "coupling_iteration", "time_s", "payload", "payload_sha256", "config_sha256",
    "slice_manifest_sha256", "consumer",
)

IDENTITY_R_GL = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MultiSliceMappingError(ValueError):
    """Base error for schema, protocol and mapping violations."""


class SchemaError(MultiSliceMappingError):
    """The object does not satisfy the 0.2.1 schema."""


class IdentityError(MultiSliceMappingError):
    """The case, slice, step or time identity is inconsistent."""


class NumericValidationError(MultiSliceMappingError):
    """A number is non-finite, out of range or inconsistent."""


class HashValidationError(MultiSliceMappingError):
    """A payload, configuration or slice-manifest digest is invalid."""


class MappingError(MultiSliceMappingError):
    """H/H^T input is incomplete, malformed or dimensionally inconsistent."""


class VirtualWorkError(MultiSliceMappingError):
    """A virtual-work audit exceeds its requested tolerance."""


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise NumericValidationError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise NumericValidationError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise NumericValidationError(f"{name} is NaN/Inf")
    return result


def _nonnegative_int(value: Any, name: str) -> int:
    number = _finite_float(value, name)
    if not number.is_integer():
        raise SchemaError(f"{name} must be an integer")
    result = int(number)
    if result < 0:
        raise NumericValidationError(f"{name} must be non-negative")
    return result


def _positive_float(value: Any, name: str) -> float:
    result = _finite_float(value, name)
    if result <= 0.0:
        raise NumericValidationError(f"{name} must be > 0")
    return result


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= tolerance * max(1.0, abs(expected))


def _require_mapping_keys(mapping: Mapping[str, Any], required: Iterable[str], context: str) -> None:
    missing = sorted(set(required).difference(mapping.keys()))
    if missing:
        raise SchemaError(f"{context}: missing fields {', '.join(missing)}")


def _schema(value: Any, context: str) -> str:
    version = str(value)
    if version in LEGACY_SCHEMA_VERSIONS:
        raise SchemaError(f"{context}: legacy schema {version} is not accepted")
    if version != SCHEMA_VERSION:
        raise SchemaError(f"{context}: expected schema {SCHEMA_VERSION}, got {version}")
    return version


def _case_id(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise IdentityError(f"{context}: case_id must be a non-empty string")
    return value


def _vector3(value: Sequence[Any], name: str) -> Tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise NumericValidationError(f"{name} must have three components")
    return tuple(_finite_float(item, f"{name}[{index}]") for index, item in enumerate(value))  # type: ignore[return-value]


def _matrix3(value: Sequence[Sequence[Any]], name: str) -> Tuple[Tuple[float, float, float], ...]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise NumericValidationError(f"{name} must be a 3x3 matrix")
    rows = []
    for i, row in enumerate(value):
        if isinstance(row, (str, bytes)) or len(row) != 3:
            raise NumericValidationError(f"{name} must be a 3x3 matrix")
        rows.append(tuple(_finite_float(item, f"{name}[{i}]") for item in row))
    return tuple(rows)  # type: ignore[return-value]


def _det3(matrix: Sequence[Sequence[float]]) -> float:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _validate_rotation(matrix: Sequence[Sequence[float]], name: str = "R_GL") -> Tuple[Tuple[float, float, float], ...]:
    result = _matrix3(matrix, name)
    for i in range(3):
        for j in range(3):
            dot = sum(result[k][i] * result[k][j] for k in range(3))
            expected = 1.0 if i == j else 0.0
            if not _close(dot, expected, DEFAULT_TOLERANCE):
                raise NumericValidationError(f"{name} columns are not orthonormal")
    if not _close(_det3(result), 1.0, DEFAULT_TOLERANCE):
        raise NumericValidationError(f"{name} determinant must be +1")
    return result


def _mat_vec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> Tuple[float, ...]:
    return tuple(sum(float(a) * float(b) for a, b in zip(row, vector)) for row in matrix)


def _transpose(matrix: Sequence[Sequence[float]]) -> Tuple[Tuple[float, ...], ...]:
    if not matrix:
        return tuple()
    return tuple(tuple(row[i] for row in matrix) for i in range(len(matrix[0])))


def local_to_global(force_local_N: Sequence[Any], R_GL: Sequence[Sequence[Any]] = IDENTITY_R_GL) -> Tuple[float, float, float]:
    """Convert a local vector to global coordinates using explicit R_GL."""

    rotation = _validate_rotation(R_GL)
    return _vector3(_mat_vec(rotation, _vector3(force_local_N, "force_local_N")), "force_global_N")


def global_to_local(force_global_N: Sequence[Any], R_GL: Sequence[Sequence[Any]] = IDENTITY_R_GL) -> Tuple[float, float, float]:
    """Convert a global vector to local coordinates using explicit R_GL^T."""

    rotation = _validate_rotation(R_GL)
    return _vector3(_mat_vec(_transpose(rotation), _vector3(force_global_N, "force_global_N")), "force_local_N")


def _plain_json(value: Any) -> Any:
    if is_dataclass(value):
        return _plain_json(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise NumericValidationError("JSON contains NaN/Inf")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return the specified compact, sorted-key UTF-8 JSON representation."""

    try:
        return json.dumps(
            _plain_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SchemaError("value is not canonical JSON serializable") from exc


def canonical_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_hash(value: Any, name: str) -> str:
    result = str(value)
    if not _SHA256_RE.fullmatch(result):
        raise HashValidationError(f"{name} must be 64 lowercase hexadecimal characters")
    return result


@dataclass(frozen=True)
class SliceDefinition:
    slice_id: int
    s_ref_m: float
    slice_length_m: float
    unit_span_m: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "slice_id", _nonnegative_int(self.slice_id, "slice_id"))
        object.__setattr__(self, "s_ref_m", _finite_float(self.s_ref_m, "s_ref_m"))
        object.__setattr__(self, "slice_length_m", _positive_float(self.slice_length_m, "slice_length_m"))
        object.__setattr__(self, "unit_span_m", _positive_float(self.unit_span_m, "unit_span_m"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SliceDefinition":
        required = ("slice_id", "s_ref_m", "slice_length_m", "unit_span_m")
        _require_mapping_keys(value, required, "slice")
        unsupported = set(value).difference(set(required))
        if unsupported:
            raise SchemaError(f"slice contains unsupported fields: {', '.join(sorted(unsupported))}")
        return cls(value["slice_id"], value["s_ref_m"], value["slice_length_m"], value["unit_span_m"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "s_ref_m": self.s_ref_m,
            "slice_length_m": self.slice_length_m,
            "unit_span_m": self.unit_span_m,
        }


@dataclass(frozen=True)
class SliceManifest:
    schema_version: str
    case_id: str
    reference_length_m: float
    represented_length_m: float
    slices: Tuple[SliceDefinition, ...]
    R_GL: Tuple[Tuple[float, float, float], ...] = IDENTITY_R_GL
    slice_manifest_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema(self.schema_version, "slice manifest"))
        object.__setattr__(self, "case_id", _case_id(self.case_id, "slice manifest"))
        object.__setattr__(self, "reference_length_m", _positive_float(self.reference_length_m, "reference_length_m"))
        object.__setattr__(self, "represented_length_m", _positive_float(self.represented_length_m, "represented_length_m"))
        converted = tuple(item if isinstance(item, SliceDefinition) else SliceDefinition.from_mapping(item) for item in self.slices)
        object.__setattr__(self, "slices", converted)
        object.__setattr__(self, "R_GL", _validate_rotation(self.R_GL))
        self._validate_core()
        if self.slice_manifest_sha256 is None:
            object.__setattr__(self, "slice_manifest_sha256", self.computed_slice_manifest_sha256())
        else:
            object.__setattr__(self, "slice_manifest_sha256", _validate_hash(self.slice_manifest_sha256, "slice_manifest_sha256"))
        self.validate(verify_hashes=True)

    def _validate_core(self) -> None:
        if not self.slices:
            raise IdentityError("slice manifest must contain at least one slice")
        ids = [item.slice_id for item in self.slices]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise IdentityError("slice_id must be unique and in ascending order after parsing")
        expected = list(range(len(self.slices)))
        if ids != expected:
            raise IdentityError(f"slice_id set must be exactly 0..{len(self.slices) - 1}")
        for item in self.slices:
            if item.s_ref_m < 0.0 or item.s_ref_m > self.reference_length_m:
                raise NumericValidationError(f"slice {item.slice_id}: s_ref_m is outside [0, reference_length_m]")
        for left, right in zip(self.slices, self.slices[1:]):
            if _close(left.s_ref_m, right.s_ref_m, S_REF_TOLERANCE):
                raise IdentityError("s_ref_m values must be unique")
        total = sum(item.slice_length_m for item in self.slices)
        if not _close(total, self.represented_length_m, DEFAULT_TOLERANCE):
            raise NumericValidationError(
                f"sum(slice_length_m)={total} does not match represented_length_m={self.represented_length_m}"
            )

    def content_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "reference_length_m": self.reference_length_m,
            "represented_length_m": self.represented_length_m,
            "R_GL": [list(row) for row in self.R_GL],
            "slices": [item.to_dict() for item in self.slices],
        }

    def computed_slice_manifest_sha256(self) -> str:
        return sha256_json(self.content_dict())

    def validate(self, verify_hashes: bool = True) -> "SliceManifest":
        self._validate_core()
        _validate_rotation(self.R_GL)
        if verify_hashes:
            if self.slice_manifest_sha256 != self.computed_slice_manifest_sha256():
                raise HashValidationError("slice_manifest_sha256 does not match canonical slice manifest")
        return self

    def to_dict(self, include_hashes: bool = True) -> Dict[str, Any]:
        result = self.content_dict()
        if include_hashes:
            result["slice_manifest_sha256"] = self.slice_manifest_sha256
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SliceManifest":
        _require_mapping_keys(
            value,
            (
                "schema_version", "case_id", "reference_length_m", "represented_length_m",
                "R_GL", "slices", "slice_manifest_sha256",
            ),
            "slice manifest",
        )
        unsupported = set(value).difference({
            "schema_version", "case_id", "reference_length_m", "represented_length_m",
            "R_GL", "slices", "slice_manifest_sha256",
        })
        if unsupported:
            raise SchemaError(f"slice manifest contains unsupported fields: {', '.join(sorted(unsupported))}")
        if not isinstance(value["slices"], (list, tuple)):
            raise SchemaError("slice manifest slices must be an array")
        raw_slices = list(value["slices"])
        parsed = tuple(SliceDefinition.from_mapping(item) for item in raw_slices)
        if len({item.slice_id for item in parsed}) != len(parsed):
            raise IdentityError("duplicate slice_id in static slice table")
        parsed = tuple(sorted(parsed, key=lambda item: item.slice_id))
        return cls(
            schema_version=value["schema_version"],
            case_id=value["case_id"],
            reference_length_m=value["reference_length_m"],
            represented_length_m=value["represented_length_m"],
            slices=parsed,
            R_GL=value["R_GL"],
            slice_manifest_sha256=value["slice_manifest_sha256"],
        )

    def slice(self, slice_id: int) -> SliceDefinition:
        sid = _nonnegative_int(slice_id, "slice_id")
        if sid >= len(self.slices):
            raise IdentityError(f"unexpected slice_id {sid}")
        item = self.slices[sid]
        if item.slice_id != sid:
            raise IdentityError(f"slice_id {sid} is missing")
        return item


@dataclass(frozen=True)
class RuntimeConfig:
    """The independent 0.2.1 run configuration.

    The configuration references a static manifest only by digest.  It never
    embeds the manifest or an arbitrary ``config`` object.
    """

    schema_version: str
    case_id: str
    dt_s: float
    timeout_s: float
    start_time_s: float
    coupling_iteration: int
    coupling_scheme: str
    slice_manifest_sha256: str
    config_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema(self.schema_version, "runtime config"))
        object.__setattr__(self, "case_id", _case_id(self.case_id, "runtime config"))
        object.__setattr__(self, "dt_s", _positive_float(self.dt_s, "dt_s"))
        object.__setattr__(self, "timeout_s", _positive_float(self.timeout_s, "timeout_s"))
        object.__setattr__(self, "start_time_s", _finite_float(self.start_time_s, "start_time_s"))
        if self.start_time_s < 0.0:
            raise NumericValidationError("start_time_s must be non-negative")
        object.__setattr__(self, "coupling_iteration", _nonnegative_int(self.coupling_iteration, "coupling_iteration"))
        if self.coupling_iteration != 0:
            raise SchemaError("current weak-coupling protocol requires coupling_iteration=0")
        if self.coupling_scheme != "explicit_weak":
            raise SchemaError("coupling_scheme must be explicit_weak")
        object.__setattr__(self, "slice_manifest_sha256", _validate_hash(self.slice_manifest_sha256, "slice_manifest_sha256"))
        if self.config_sha256 is None:
            object.__setattr__(self, "config_sha256", self.computed_config_sha256())
        else:
            object.__setattr__(self, "config_sha256", _validate_hash(self.config_sha256, "config_sha256"))
        self.validate(verify_hash=True)

    def content_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "dt_s": self.dt_s,
            "timeout_s": self.timeout_s,
            "start_time_s": self.start_time_s,
            "coupling_iteration": self.coupling_iteration,
            "coupling_scheme": self.coupling_scheme,
            "slice_manifest_sha256": self.slice_manifest_sha256,
        }

    def computed_config_sha256(self) -> str:
        return sha256_json(self.content_dict())

    def validate(self, verify_hash: bool = True) -> "RuntimeConfig":
        if verify_hash and self.config_sha256 != self.computed_config_sha256():
            raise HashValidationError("config_sha256 does not match canonical runtime config")
        return self

    def validate_against_manifest(self, manifest: SliceManifest) -> "RuntimeConfig":
        manifest.validate()
        self.validate()
        if self.case_id != manifest.case_id:
            raise IdentityError("runtime config case_id mismatch")
        if self.slice_manifest_sha256 != manifest.slice_manifest_sha256:
            raise HashValidationError("runtime config slice_manifest_sha256 mismatch")
        return self

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        result = self.content_dict()
        if include_hash:
            result["config_sha256"] = self.config_sha256
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RuntimeConfig":
        required = (
            "schema_version", "case_id", "dt_s", "timeout_s", "start_time_s",
            "coupling_iteration", "coupling_scheme", "slice_manifest_sha256", "config_sha256",
        )
        _require_mapping_keys(value, required, "runtime config")
        unsupported = set(value).difference(set(required))
        if unsupported:
            raise SchemaError(f"runtime config contains unsupported fields: {', '.join(sorted(unsupported))}")
        return cls(**{key: value[key] for key in required})


@dataclass(frozen=True)
class ForceConversion:
    openfoam_force_N: Tuple[float, float, float]
    unit_span_m: float
    force_2d_Npm: Tuple[float, float, float]
    slice_length_m: float
    force_N: Tuple[float, float, float]
    force_local_N: Tuple[float, float, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "openfoam_force_N": list(self.openfoam_force_N),
            "unit_span_m": self.unit_span_m,
            "force_2d_Npm": list(self.force_2d_Npm),
            "slice_length_m": self.slice_length_m,
            "force_N": list(self.force_N),
            "force_local_N": list(self.force_local_N),
        }


def convert_openfoam_force(
    openfoam_force_N: Sequence[Any],
    unit_span_m: Any,
    slice_length_m: Any,
    R_GL: Sequence[Sequence[Any]] = IDENTITY_R_GL,
) -> ForceConversion:
    """Convert OpenFOAM total force to 2-D and integrated slice levels once."""

    openfoam = _vector3(openfoam_force_N, "openfoam_force_N")
    unit_span = _positive_float(unit_span_m, "unit_span_m")
    slice_length = _positive_float(slice_length_m, "slice_length_m")
    force_2d = tuple(value / unit_span for value in openfoam)
    force_global = tuple(value * slice_length for value in force_2d)
    force_local = global_to_local(force_global, R_GL)
    return ForceConversion(openfoam, unit_span, force_2d, slice_length, force_global, force_local)


def _force_conversion_relative_error(actual: float, expected: float) -> float:
    return abs(actual - expected) / max(1.0, abs(expected), abs(actual))


@dataclass(frozen=True)
class MotionRecord:
    schema_version: str
    case_id: str
    step: int
    coupling_iteration: int
    time_s: float
    slice_id: int
    s_ref_m: float
    slice_length_m: float
    x_ref_m: float
    y_ref_m: float
    z_ref_m: float
    ux_m: float
    uy_m: float
    uz_m: float
    x_m: float
    y_m: float
    z_m: float
    vx_mps: float
    vy_mps: float
    vz_mps: float
    ax_mps2: float
    ay_mps2: float
    az_mps2: float
    status: str = "complete"

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema(self.schema_version, "motion"))
        object.__setattr__(self, "case_id", _case_id(self.case_id, "motion"))
        object.__setattr__(self, "step", _nonnegative_int(self.step, "step"))
        object.__setattr__(self, "coupling_iteration", _nonnegative_int(self.coupling_iteration, "coupling_iteration"))
        if self.coupling_iteration != 0:
            raise SchemaError("current weak-coupling protocol requires coupling_iteration=0")
        object.__setattr__(self, "time_s", _finite_float(self.time_s, "time_s"))
        if self.time_s < 0.0:
            raise NumericValidationError("time_s must be non-negative")
        object.__setattr__(self, "slice_id", _nonnegative_int(self.slice_id, "slice_id"))
        object.__setattr__(self, "s_ref_m", _finite_float(self.s_ref_m, "s_ref_m"))
        object.__setattr__(self, "slice_length_m", _positive_float(self.slice_length_m, "slice_length_m"))
        for name in (
            "x_ref_m", "y_ref_m", "z_ref_m", "ux_m", "uy_m", "uz_m", "x_m", "y_m", "z_m",
            "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2",
        ):
            object.__setattr__(self, name, _finite_float(getattr(self, name), name))
        if self.status != "complete":
            raise SchemaError("motion status must be complete")
        for absolute, reference, displacement, name in (
            (self.x_m, self.x_ref_m, self.ux_m, "x_m"),
            (self.y_m, self.y_ref_m, self.uy_m, "y_m"),
            (self.z_m, self.z_ref_m, self.uz_m, "z_m"),
        ):
            if abs(absolute - (reference + displacement)) > GEOMETRY_TOLERANCE * max(1.0, abs(absolute)):
                raise NumericValidationError(f"motion {name} != reference + displacement")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MotionRecord":
        _require_mapping_keys(value, MOTION_FIELDS, "motion")
        return cls(**{key: value[key] for key in MOTION_FIELDS})

    def to_dict(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in MOTION_FIELDS}


@dataclass(frozen=True)
class LoadRecord:
    schema_version: str
    case_id: str
    step: int
    coupling_iteration: int
    time_s: float
    slice_id: int
    s_ref_m: float
    slice_length_m: float
    unit_span_m: float
    force_representation: str
    openfoam_force_x_N: float
    openfoam_force_y_N: float
    openfoam_force_z_N: float
    force_2d_x_Npm: float
    force_2d_y_Npm: float
    force_2d_z_Npm: float
    force_x_N: float
    force_y_N: float
    force_z_N: float
    force_local_streamwise_N: float
    force_local_crossflow_N: float
    force_local_axial_N: float
    cfd_time_step_s: float
    status: str = "complete"

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema(self.schema_version, "load"))
        object.__setattr__(self, "case_id", _case_id(self.case_id, "load"))
        object.__setattr__(self, "step", _nonnegative_int(self.step, "step"))
        object.__setattr__(self, "coupling_iteration", _nonnegative_int(self.coupling_iteration, "coupling_iteration"))
        if self.coupling_iteration != 0:
            raise SchemaError("current weak-coupling protocol requires coupling_iteration=0")
        object.__setattr__(self, "time_s", _finite_float(self.time_s, "time_s"))
        if self.time_s < 0.0:
            raise NumericValidationError("time_s must be non-negative")
        object.__setattr__(self, "slice_id", _nonnegative_int(self.slice_id, "slice_id"))
        object.__setattr__(self, "s_ref_m", _finite_float(self.s_ref_m, "s_ref_m"))
        object.__setattr__(self, "slice_length_m", _positive_float(self.slice_length_m, "slice_length_m"))
        object.__setattr__(self, "unit_span_m", _positive_float(self.unit_span_m, "unit_span_m"))
        if self.force_representation != "integrated_slice_force_N":
            raise SchemaError("force_representation must be integrated_slice_force_N")
        for name in LOAD_FIELDS[10:-1]:
            object.__setattr__(self, name, _finite_float(getattr(self, name), name))
        object.__setattr__(self, "cfd_time_step_s", _positive_float(self.cfd_time_step_s, "cfd_time_step_s"))
        if self.status != "complete":
            raise SchemaError("load status must be complete")
        openfoam = (self.openfoam_force_x_N, self.openfoam_force_y_N, self.openfoam_force_z_N)
        force_2d = (self.force_2d_x_Npm, self.force_2d_y_Npm, self.force_2d_z_Npm)
        force = (self.force_x_N, self.force_y_N, self.force_z_N)
        expected_2d = tuple(value / self.unit_span_m for value in openfoam)
        expected_force = tuple(value * self.slice_length_m for value in expected_2d)
        for actual, expected, name in zip(force_2d, expected_2d, ("x", "y", "z")):
            if _force_conversion_relative_error(actual, expected) > FORCE_TOLERANCE:
                raise NumericValidationError(f"force_2d_{name}_Npm is inconsistent with OpenFOAM force")
        for actual, expected, name in zip(force, expected_force, ("x", "y", "z")):
            if _force_conversion_relative_error(actual, expected) > FORCE_TOLERANCE:
                raise NumericValidationError(f"force_{name}_N is inconsistent with slice_length_m conversion")

    @classmethod
    def from_conversion(
        cls,
        *,
        case_id: str,
        step: int,
        time_s: float,
        slice_definition: SliceDefinition,
        unit_span_m: float,
        openfoam_force_N: Sequence[Any],
        cfd_time_step_s: float,
        R_GL: Sequence[Sequence[Any]] = IDENTITY_R_GL,
    ) -> "LoadRecord":
        requested_span = _positive_float(unit_span_m, "unit_span_m")
        if not _close(requested_span, slice_definition.unit_span_m, DEFAULT_TOLERANCE):
            raise IdentityError("unit_span_m does not match the static slice definition")
        conversion = convert_openfoam_force(
            openfoam_force_N, requested_span, slice_definition.slice_length_m, R_GL
        )
        return cls(
            schema_version=SCHEMA_VERSION,
            case_id=case_id,
            step=step,
            coupling_iteration=0,
            time_s=time_s,
            slice_id=slice_definition.slice_id,
            s_ref_m=slice_definition.s_ref_m,
            slice_length_m=slice_definition.slice_length_m,
            unit_span_m=conversion.unit_span_m,
            force_representation="integrated_slice_force_N",
            openfoam_force_x_N=conversion.openfoam_force_N[0],
            openfoam_force_y_N=conversion.openfoam_force_N[1],
            openfoam_force_z_N=conversion.openfoam_force_N[2],
            force_2d_x_Npm=conversion.force_2d_Npm[0],
            force_2d_y_Npm=conversion.force_2d_Npm[1],
            force_2d_z_Npm=conversion.force_2d_Npm[2],
            force_x_N=conversion.force_N[0],
            force_y_N=conversion.force_N[1],
            force_z_N=conversion.force_N[2],
            force_local_streamwise_N=conversion.force_local_N[0],
            force_local_crossflow_N=conversion.force_local_N[1],
            force_local_axial_N=conversion.force_local_N[2],
            cfd_time_step_s=cfd_time_step_s,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        R_GL: Sequence[Sequence[Any]] = IDENTITY_R_GL,
    ) -> "LoadRecord":
        _require_mapping_keys(value, LOAD_FIELDS, "load")
        record = cls(**{key: value[key] for key in LOAD_FIELDS})
        record.validate_rotation(R_GL)
        return record

    @property
    def openfoam_force_N(self) -> Tuple[float, float, float]:
        return (self.openfoam_force_x_N, self.openfoam_force_y_N, self.openfoam_force_z_N)

    @property
    def force_2d_Npm(self) -> Tuple[float, float, float]:
        return (self.force_2d_x_Npm, self.force_2d_y_Npm, self.force_2d_z_Npm)

    @property
    def force_N(self) -> Tuple[float, float, float]:
        return (self.force_x_N, self.force_y_N, self.force_z_N)

    @property
    def force_local_N(self) -> Tuple[float, float, float]:
        return (self.force_local_streamwise_N, self.force_local_crossflow_N, self.force_local_axial_N)

    def validate_rotation(self, R_GL: Sequence[Sequence[Any]]) -> "LoadRecord":
        expected = global_to_local(self.force_N, R_GL)
        for actual, wanted, name in zip(self.force_local_N, expected, ("streamwise", "crossflow", "axial")):
            if _force_conversion_relative_error(actual, wanted) > FORCE_TOLERANCE:
                raise NumericValidationError(f"force_local_{name}_N is inconsistent with R_GL^T force_N")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in LOAD_FIELDS}


def _validate_record_identity(
    record: Union[MotionRecord, LoadRecord],
    manifest: SliceManifest,
    expected_step: Optional[int] = None,
    expected_time_s: Optional[float] = None,
) -> None:
    definition = manifest.slice(record.slice_id)
    if record.case_id != manifest.case_id:
        raise IdentityError(f"slice {record.slice_id}: case_id mismatch")
    if not _close(record.s_ref_m, definition.s_ref_m, S_REF_TOLERANCE):
        raise IdentityError(f"slice {record.slice_id}: s_ref_m mismatch")
    if not _close(record.slice_length_m, definition.slice_length_m, DEFAULT_TOLERANCE):
        raise IdentityError(f"slice {record.slice_id}: slice_length_m mismatch")
    if expected_step is not None and record.step != _nonnegative_int(expected_step, "expected_step"):
        raise IdentityError(f"slice {record.slice_id}: step mismatch")
    if expected_time_s is not None:
        expected = _finite_float(expected_time_s, "expected_time_s")
        if not _close(record.time_s, expected, TIME_TOLERANCE):
            raise IdentityError(f"slice {record.slice_id}: time_s mismatch")
    if record.coupling_iteration != 0:
        raise IdentityError("coupling_iteration must be zero in Draft 2")


def validate_motion_record(
    record: MotionRecord,
    manifest: SliceManifest,
    expected_step: Optional[int] = None,
    expected_time_s: Optional[float] = None,
) -> MotionRecord:
    manifest.validate()
    _validate_record_identity(record, manifest, expected_step, expected_time_s)
    return record


def validate_load_record(
    record: LoadRecord,
    manifest: SliceManifest,
    expected_step: Optional[int] = None,
    expected_time_s: Optional[float] = None,
) -> LoadRecord:
    manifest.validate()
    record.validate_rotation(manifest.R_GL)
    _validate_record_identity(record, manifest, expected_step, expected_time_s)
    definition = manifest.slice(record.slice_id)
    if not _close(record.unit_span_m, definition.unit_span_m, DEFAULT_TOLERANCE):
        raise IdentityError(f"slice {record.slice_id}: unit_span_m mismatch")
    return record


def validate_record_transaction(
    records: Iterable[Union[MotionRecord, LoadRecord]],
    manifest: SliceManifest,
    *,
    kind: str,
    expected_step: Optional[int] = None,
    expected_time_s: Optional[float] = None,
) -> Dict[int, Union[MotionRecord, LoadRecord]]:
    """Validate a complete transaction and restore standard slice_id order."""

    expected_ids = {item.slice_id for item in manifest.slices}
    by_id: Dict[int, Union[MotionRecord, LoadRecord]] = {}
    metadata: Optional[Tuple[str, int, int, float]] = None
    for record in records:
        if kind == "motion" and not isinstance(record, MotionRecord):
            raise SchemaError("motion transaction contains a non-motion record")
        if kind == "load" and not isinstance(record, LoadRecord):
            raise SchemaError("load transaction contains a non-load record")
        if record.slice_id in by_id:
            raise IdentityError(f"duplicate slice_id {record.slice_id}")
        if isinstance(record, MotionRecord):
            validate_motion_record(record, manifest, expected_step, expected_time_s)
        else:
            validate_load_record(record, manifest, expected_step, expected_time_s)
        current = (record.case_id, record.step, record.coupling_iteration, record.time_s)
        if metadata is None:
            metadata = current
        elif current[:3] != metadata[:3] or not _close(current[3], metadata[3], TIME_TOLERANCE):
            raise IdentityError("step/time/coupling metadata must be identical for all slices")
        by_id[record.slice_id] = record
    if set(by_id) != expected_ids:
        missing = sorted(expected_ids.difference(by_id))
        unexpected = sorted(set(by_id).difference(expected_ids))
        raise IdentityError(f"incomplete slice transaction; missing={missing}, unexpected={unexpected}")
    return {sid: by_id[sid] for sid in sorted(by_id)}


@dataclass(frozen=True)
class ReadyMarker:
    schema_version: str
    marker_type: str
    payload_kind: str
    case_id: str
    slice_id: int
    step: int
    coupling_iteration: int
    time_s: float
    payload: str
    row_count: int
    payload_sha256: str
    config_sha256: str
    slice_manifest_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema(self.schema_version, "ready marker"))
        if self.marker_type != "ready":
            raise SchemaError("marker_type must be ready")
        if self.payload_kind not in ("motion", "load"):
            raise SchemaError("payload_kind must be motion or load")
        object.__setattr__(self, "case_id", _case_id(self.case_id, "ready marker"))
        object.__setattr__(self, "slice_id", _nonnegative_int(self.slice_id, "slice_id"))
        object.__setattr__(self, "step", _nonnegative_int(self.step, "step"))
        object.__setattr__(self, "coupling_iteration", _nonnegative_int(self.coupling_iteration, "coupling_iteration"))
        if self.coupling_iteration != 0:
            raise SchemaError("current weak-coupling protocol requires coupling_iteration=0")
        object.__setattr__(self, "time_s", _finite_float(self.time_s, "time_s"))
        if self.time_s < 0.0:
            raise NumericValidationError("time_s must be non-negative")
        if not isinstance(self.payload, str) or not self.payload:
            raise SchemaError("payload must be a non-empty file name")
        object.__setattr__(self, "row_count", _nonnegative_int(self.row_count, "row_count"))
        if self.row_count != 1:
            raise SchemaError("Draft 2 slice payload row_count must be 1")
        object.__setattr__(self, "payload_sha256", _validate_hash(self.payload_sha256, "payload_sha256"))
        object.__setattr__(self, "config_sha256", _validate_hash(self.config_sha256, "config_sha256"))
        object.__setattr__(self, "slice_manifest_sha256", _validate_hash(self.slice_manifest_sha256, "slice_manifest_sha256"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReadyMarker":
        _require_mapping_keys(value, READY_FIELDS, "ready marker")
        return cls(**{key: value[key] for key in READY_FIELDS})

    def to_dict(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in READY_FIELDS}

    def validate_against(
        self,
        manifest: SliceManifest,
        runtime_config: RuntimeConfig,
        *,
        expected_step: Optional[int] = None,
        expected_time_s: Optional[float] = None,
        payload_path: Optional[Union[str, Path]] = None,
    ) -> "ReadyMarker":
        manifest.validate()
        runtime_config.validate_against_manifest(manifest)
        manifest.slice(self.slice_id)
        if self.case_id != manifest.case_id:
            raise IdentityError("ready marker case_id mismatch")
        if self.config_sha256 != runtime_config.config_sha256:
            raise HashValidationError("ready marker config_sha256 mismatch")
        if self.slice_manifest_sha256 != manifest.slice_manifest_sha256:
            raise HashValidationError("ready marker slice_manifest_sha256 mismatch")
        if expected_step is not None and self.step != _nonnegative_int(expected_step, "expected_step"):
            raise IdentityError("ready marker step mismatch")
        if expected_time_s is not None and not _close(self.time_s, _finite_float(expected_time_s, "expected_time_s"), TIME_TOLERANCE):
            raise IdentityError("ready marker time_s mismatch")
        if payload_path is not None:
            actual = sha256_file(payload_path)
            if actual != self.payload_sha256:
                raise HashValidationError("payload_sha256 mismatch")
            if Path(payload_path).name != self.payload:
                raise IdentityError("ready marker payload name mismatch")
        return self


@dataclass(frozen=True)
class ConsumedMarker:
    schema_version: str
    marker_type: str
    payload_kind: str
    case_id: str
    slice_id: int
    step: int
    coupling_iteration: int
    time_s: float
    payload: str
    payload_sha256: str
    config_sha256: str
    slice_manifest_sha256: str
    consumer: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema(self.schema_version, "consumed marker"))
        if self.marker_type != "consumed":
            raise SchemaError("marker_type must be consumed")
        if self.payload_kind not in ("motion", "load"):
            raise SchemaError("payload_kind must be motion or load")
        object.__setattr__(self, "case_id", _case_id(self.case_id, "consumed marker"))
        object.__setattr__(self, "slice_id", _nonnegative_int(self.slice_id, "slice_id"))
        object.__setattr__(self, "step", _nonnegative_int(self.step, "step"))
        object.__setattr__(self, "coupling_iteration", _nonnegative_int(self.coupling_iteration, "coupling_iteration"))
        if self.coupling_iteration != 0:
            raise SchemaError("current weak-coupling protocol requires coupling_iteration=0")
        object.__setattr__(self, "time_s", _finite_float(self.time_s, "time_s"))
        if self.time_s < 0.0:
            raise NumericValidationError("time_s must be non-negative")
        if not isinstance(self.payload, str) or not self.payload:
            raise SchemaError("payload must be a non-empty file name")
        object.__setattr__(self, "payload_sha256", _validate_hash(self.payload_sha256, "payload_sha256"))
        object.__setattr__(self, "config_sha256", _validate_hash(self.config_sha256, "config_sha256"))
        object.__setattr__(self, "slice_manifest_sha256", _validate_hash(self.slice_manifest_sha256, "slice_manifest_sha256"))
        if not isinstance(self.consumer, str) or not self.consumer:
            raise SchemaError("consumer must be a non-empty string")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConsumedMarker":
        _require_mapping_keys(value, CONSUMED_FIELDS, "consumed marker")
        return cls(**{key: value[key] for key in CONSUMED_FIELDS})

    def to_dict(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in CONSUMED_FIELDS}

    def validate_against(
        self,
        manifest: SliceManifest,
        runtime_config: RuntimeConfig,
        *,
        expected_step: Optional[int] = None,
        expected_time_s: Optional[float] = None,
        payload_path: Optional[Union[str, Path]] = None,
    ) -> "ConsumedMarker":
        manifest.validate()
        runtime_config.validate_against_manifest(manifest)
        manifest.slice(self.slice_id)
        if self.case_id != manifest.case_id:
            raise IdentityError("consumed marker case_id mismatch")
        if self.config_sha256 != runtime_config.config_sha256:
            raise HashValidationError("consumed marker config_sha256 mismatch")
        if self.slice_manifest_sha256 != manifest.slice_manifest_sha256:
            raise HashValidationError("consumed marker slice_manifest_sha256 mismatch")
        if expected_step is not None and self.step != _nonnegative_int(expected_step, "expected_step"):
            raise IdentityError("consumed marker step mismatch")
        if expected_time_s is not None and not _close(self.time_s, _finite_float(expected_time_s, "expected_time_s"), TIME_TOLERANCE):
            raise IdentityError("consumed marker time_s mismatch")
        if payload_path is not None:
            if Path(payload_path).name != self.payload:
                raise IdentityError("consumed marker payload name mismatch")
            if sha256_file(payload_path) != self.payload_sha256:
                raise HashValidationError("consumed marker payload_sha256 mismatch")
        return self


def atomic_write_json(path: Union[str, Path], payload: Mapping[str, Any]) -> None:
    """Atomically write a canonical JSON document with flush/fsync/replace."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + target.name + ".", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    temporary_path = Path(temporary)
    fast_exchange = _ephemeral_atomic_path(target)
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(payload))
            stream.write("\n")
            stream.flush()
            if not fast_exchange:
                os.fsync(stream.fileno())
        os.replace(str(temporary_path), str(target))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def atomic_write_csv(path: Union[str, Path], fieldnames: Sequence[str], row: Mapping[str, Any]) -> None:
    """Atomically write one UTF-8 Draft-2 CSV row."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + target.name + ".", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    temporary_path = Path(temporary)
    fast_exchange = _ephemeral_atomic_path(target)
    try:
        with temporary_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(fieldnames), extrasaction="raise")
            writer.writeheader()
            writer.writerow(dict(row))
            stream.flush()
            if not fast_exchange:
                os.fsync(stream.fileno())
        os.replace(str(temporary_path), str(target))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def create_ready_marker(
    payload_path: Union[str, Path],
    record: Union[MotionRecord, LoadRecord],
    manifest: SliceManifest,
    runtime_config: RuntimeConfig,
    *,
    payload_kind: str,
) -> ReadyMarker:
    if payload_kind not in ("motion", "load"):
        raise SchemaError("payload_kind must be motion or load")
    if payload_kind == "motion" and not isinstance(record, MotionRecord):
        raise SchemaError("motion payload requires MotionRecord")
    if payload_kind == "load" and not isinstance(record, LoadRecord):
        raise SchemaError("load payload requires LoadRecord")
    runtime_config.validate_against_manifest(manifest)
    if isinstance(record, MotionRecord):
        validate_motion_record(record, manifest)
    else:
        validate_load_record(record, manifest)
    path = Path(payload_path)
    return ReadyMarker(
        schema_version=SCHEMA_VERSION,
        marker_type="ready",
        payload_kind=payload_kind,
        case_id=manifest.case_id,
        slice_id=record.slice_id,
        step=record.step,
        coupling_iteration=record.coupling_iteration,
        time_s=record.time_s,
        payload=path.name,
        row_count=1,
        payload_sha256=sha256_file(path),
        config_sha256=runtime_config.config_sha256 or runtime_config.computed_config_sha256(),
        slice_manifest_sha256=manifest.slice_manifest_sha256 or manifest.computed_slice_manifest_sha256(),
    )


def create_consumed_marker(
    ready: ReadyMarker,
    manifest: SliceManifest,
    runtime_config: RuntimeConfig,
    consumer: str,
    *,
    payload_path: Union[str, Path],
) -> ConsumedMarker:
    """Create a consumed marker only after rechecking the payload bytes."""

    ready.validate_against(manifest, runtime_config, payload_path=payload_path)
    return ConsumedMarker(
        schema_version=SCHEMA_VERSION,
        marker_type="consumed",
        payload_kind=ready.payload_kind,
        case_id=ready.case_id,
        slice_id=ready.slice_id,
        step=ready.step,
        coupling_iteration=ready.coupling_iteration,
        time_s=ready.time_s,
        payload=ready.payload,
        payload_sha256=ready.payload_sha256,
        config_sha256=ready.config_sha256,
        slice_manifest_sha256=ready.slice_manifest_sha256,
        consumer=consumer,
    )


def _read_one_csv(path: Union[str, Path], fields: Sequence[str]) -> Dict[str, str]:
    payload = Path(path)
    if not payload.is_file():
        raise SchemaError(f"missing payload: {payload}")
    with payload.open("r", newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        actual = list(reader.fieldnames or [])
        _require_mapping_keys({key: None for key in actual}, fields, str(payload))
        rows = list(reader)
    if len(rows) != 1:
        raise SchemaError(f"{payload}: Draft 2 payload must contain exactly one data row")
    return rows[0]


def read_motion_csv(
    path: Union[str, Path],
    manifest: SliceManifest,
    *,
    expected_step: Optional[int] = None,
    expected_time_s: Optional[float] = None,
    runtime_config: Optional[RuntimeConfig] = None,
    ready_marker: Optional[ReadyMarker] = None,
) -> MotionRecord:
    record = MotionRecord.from_mapping(_read_one_csv(path, MOTION_FIELDS))
    validate_motion_record(record, manifest, expected_step, expected_time_s)
    if ready_marker is not None:
        if runtime_config is None:
            raise SchemaError("runtime_config is required for marker validation")
        ready_marker.validate_against(manifest, runtime_config, expected_step=expected_step, expected_time_s=expected_time_s, payload_path=path)
        if (
            ready_marker.payload_kind != "motion"
            or ready_marker.slice_id != record.slice_id
            or ready_marker.case_id != record.case_id
            or ready_marker.step != record.step
            or ready_marker.coupling_iteration != record.coupling_iteration
            or not _close(ready_marker.time_s, record.time_s, TIME_TOLERANCE)
        ):
            raise IdentityError("ready marker does not identify the motion record")
    return record


def read_load_csv(
    path: Union[str, Path],
    manifest: SliceManifest,
    *,
    expected_step: Optional[int] = None,
    expected_time_s: Optional[float] = None,
    runtime_config: Optional[RuntimeConfig] = None,
    ready_marker: Optional[ReadyMarker] = None,
) -> LoadRecord:
    record = LoadRecord.from_mapping(_read_one_csv(path, LOAD_FIELDS), manifest.R_GL)
    validate_load_record(record, manifest, expected_step, expected_time_s)
    if ready_marker is not None:
        if runtime_config is None:
            raise SchemaError("runtime_config is required for marker validation")
        ready_marker.validate_against(manifest, runtime_config, expected_step=expected_step, expected_time_s=expected_time_s, payload_path=path)
        if (
            ready_marker.payload_kind != "load"
            or ready_marker.slice_id != record.slice_id
            or ready_marker.case_id != record.case_id
            or ready_marker.step != record.step
            or ready_marker.coupling_iteration != record.coupling_iteration
            or not _close(ready_marker.time_s, record.time_s, TIME_TOLERANCE)
        ):
            raise IdentityError("ready marker does not identify the load record")
    return record


def _validate_mesh_nodes(mesh_nodes: Sequence[Any], reference_length_m: Optional[float] = None) -> Tuple[float, ...]:
    if isinstance(mesh_nodes, (str, bytes)) or len(mesh_nodes) < 2:
        raise MappingError("mesh_nodes must contain at least two coordinates")
    nodes = tuple(_finite_float(item, "mesh_nodes") for item in mesh_nodes)
    if abs(nodes[0]) > GEOMETRY_TOLERANCE:
        raise MappingError("mesh_nodes must start at s=0")
    for left, right in zip(nodes, nodes[1:]):
        if right <= left:
            raise MappingError("mesh_nodes must be strictly increasing")
    if reference_length_m is not None and not _close(nodes[-1], reference_length_m, S_REF_TOLERANCE):
        raise MappingError("mesh_nodes end does not match manifest reference_length_m")
    return nodes


def _hermite_shape_values(x: float, length: float) -> Tuple[float, float, float, float]:
    xi = x / length
    return (
        1.0 - 3.0 * xi * xi + 2.0 * xi * xi * xi,
        length * (xi - 2.0 * xi * xi + xi * xi * xi),
        3.0 * xi * xi - 2.0 * xi * xi * xi,
        length * (-xi * xi + xi * xi * xi),
    )


def ancf_hermite_H(
    s_ref_m: Any,
    mesh_nodes: Sequence[Any],
    *,
    ndof: Optional[int] = None,
) -> Tuple[Tuple[float, ...], ...]:
    """Build the confirmed ANCF H3 row block for one reference location.

    Each node occupies six global coordinates ``[r_x,r_y,r_z,r_sx,r_sy,r_sz]``.
    The returned matrix has three rows and maps the full global q to
    ``[x,y,z]``.  Non-uniform meshes, node coincidences and multiple locations
    in one element are handled by the location itself, not by row order.
    """

    nodes = _validate_mesh_nodes(mesh_nodes)
    s = _finite_float(s_ref_m, "s_ref_m")
    if s < nodes[0] - S_REF_TOLERANCE or s > nodes[-1] + S_REF_TOLERANCE:
        raise MappingError("s_ref_m lies outside the ANCF mesh")
    s = min(max(s, nodes[0]), nodes[-1])
    expected_ndof = 6 * len(nodes)
    if ndof is None:
        ndof = expected_ndof
    ndof = _nonnegative_int(ndof, "ndof")
    if ndof < expected_ndof:
        raise MappingError(f"ndof={ndof} is smaller than the ANCF mesh requirement {expected_ndof}")
    if s >= nodes[-1]:
        element = len(nodes) - 2
    else:
        element = min(bisect_right(nodes, s) - 1, len(nodes) - 2)
    length = nodes[element + 1] - nodes[element]
    x = s - nodes[element]
    shape = _hermite_shape_values(x, length)
    matrix = [[0.0 for _ in range(ndof)] for _ in range(3)]
    starts = (6 * element, 6 * element + 3, 6 * (element + 1), 6 * (element + 1) + 3)
    for coefficient, start in zip(shape, starts):
        for component in range(3):
            matrix[component][start + component] = coefficient
    return tuple(tuple(row) for row in matrix)


def build_H_for_manifest(
    manifest: SliceManifest,
    mesh_nodes: Sequence[Any],
    *,
    ndof: Optional[int] = None,
) -> Dict[int, Tuple[Tuple[float, ...], ...]]:
    manifest.validate()
    _validate_mesh_nodes(mesh_nodes, manifest.reference_length_m)
    return {
        item.slice_id: ancf_hermite_H(item.s_ref_m, mesh_nodes, ndof=ndof)
        for item in manifest.slices
    }


def interpolate_ancf_state(
    H: Sequence[Sequence[Any]],
    q: Sequence[Any],
    qdot: Sequence[Any],
    qddot: Sequence[Any],
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]:
    """Return r, v and a using the same H matrix for all three states."""

    matrix = _validate_H(H, "H")
    ndof = len(matrix[0])
    vectors = []
    for value, name in ((q, "q"), (qdot, "qdot"), (qddot, "qddot")):
        if len(value) != ndof:
            raise MappingError(f"{name} length does not match H")
        vectors.append(_vector3(_mat_vec(matrix, tuple(_finite_float(item, name) for item in value)), name + "_slice"))
    return vectors[0], vectors[1], vectors[2]  # type: ignore[return-value]


def motion_from_ancf_state(
    manifest: SliceManifest,
    slice_id: int,
    H: Sequence[Sequence[Any]],
    q: Sequence[Any],
    qdot: Sequence[Any],
    qddot: Sequence[Any],
    *,
    step: int,
    time_s: float,
    reference_position_m: Optional[Sequence[Any]] = None,
    case_id: Optional[str] = None,
) -> MotionRecord:
    definition = manifest.slice(slice_id)
    reference = _vector3(reference_position_m if reference_position_m is not None else (0.0, 0.0, definition.s_ref_m), "reference_position_m")
    position, velocity, acceleration = interpolate_ancf_state(H, q, qdot, qddot)
    displacement = tuple(position[i] - reference[i] for i in range(3))
    return MotionRecord(
        schema_version=SCHEMA_VERSION,
        case_id=manifest.case_id if case_id is None else case_id,
        step=step,
        coupling_iteration=0,
        time_s=time_s,
        slice_id=definition.slice_id,
        s_ref_m=definition.s_ref_m,
        slice_length_m=definition.slice_length_m,
        x_ref_m=reference[0], y_ref_m=reference[1], z_ref_m=reference[2],
        ux_m=displacement[0], uy_m=displacement[1], uz_m=displacement[2],
        x_m=position[0], y_m=position[1], z_m=position[2],
        vx_mps=velocity[0], vy_mps=velocity[1], vz_mps=velocity[2],
        ax_mps2=acceleration[0], ay_mps2=acceleration[1], az_mps2=acceleration[2],
    )


def _validate_H(H: Sequence[Sequence[Any]], name: str) -> Tuple[Tuple[float, ...], ...]:
    if isinstance(H, (str, bytes)) or len(H) != 3:
        raise MappingError(f"{name} must have shape 3 x ndof")
    rows = []
    for i, row in enumerate(H):
        if isinstance(row, (str, bytes)) or len(row) == 0:
            raise MappingError(f"{name} must have shape 3 x ndof")
        rows.append(tuple(_finite_float(item, f"{name}[{i}]") for item in row))
    if len({len(row) for row in rows}) != 1:
        raise MappingError(f"{name} rows have inconsistent lengths")
    return tuple(rows)


def _force_vector(value: Any, name: str) -> Tuple[float, float, float]:
    if isinstance(value, LoadRecord):
        return value.force_N
    if isinstance(value, ForceConversion):
        return value.force_N
    return _vector3(value, name)


@dataclass(frozen=True)
class VirtualWorkAudit:
    W_slice_J: float
    W_generalized_J: float
    error_abs_J: float
    error_rel: float
    random_seed: Optional[int]
    slice_count: int
    structure_dof_count: int
    slices: Tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "W_slice_J": self.W_slice_J,
            "W_generalized_J": self.W_generalized_J,
            "error_abs_J": self.error_abs_J,
            "error_rel": self.error_rel,
            "random_seed": self.random_seed,
            "slice_count": self.slice_count,
            "structure_dof_count": self.structure_dof_count,
            "slices": [dict(item) for item in self.slices],
        }


@dataclass(frozen=True)
class GeneralizedForceResult:
    generalized_force: Tuple[float, ...]
    slice_contributions: Mapping[int, Tuple[float, ...]]
    force_audit: Mapping[int, Mapping[str, Any]]
    virtual_work: Optional[VirtualWorkAudit]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generalized_force": list(self.generalized_force),
            "slice_contributions": {str(key): list(value) for key, value in self.slice_contributions.items()},
            "force_audit": {str(key): dict(value) for key, value in self.force_audit.items()},
            "virtual_work": None if self.virtual_work is None else self.virtual_work.to_dict(),
        }


def map_integrated_slice_forces(
    manifest: SliceManifest,
    H_by_slice_id: Mapping[int, Sequence[Sequence[Any]]],
    force_by_slice_id: Mapping[int, Any],
    *,
    delta_q: Optional[Sequence[Any]] = None,
    random_seed: Optional[int] = None,
) -> GeneralizedForceResult:
    """Compute Q = sum(H_i^T F_i) with no hidden slice-length factor."""

    manifest.validate()
    expected_ids = {item.slice_id for item in manifest.slices}
    if set(H_by_slice_id) != expected_ids:
        raise MappingError("H_by_slice_id must contain exactly the manifest slice_id set")
    if set(force_by_slice_id) != expected_ids:
        raise MappingError("force_by_slice_id must contain exactly the manifest slice_id set")
    matrices = {sid: _validate_H(H_by_slice_id[sid], f"H[{sid}]") for sid in expected_ids}
    ndof = len(matrices[next(iter(expected_ids))][0])
    if any(len(matrix[0]) != ndof for matrix in matrices.values()):
        raise MappingError("all H matrices must have the same structure DOF count")
    vectors = {sid: _force_vector(force_by_slice_id[sid], f"force[{sid}]") for sid in expected_ids}
    generalized = [0.0] * ndof
    contributions: Dict[int, Tuple[float, ...]] = {}
    audits: Dict[int, Mapping[str, Any]] = {}
    for item in manifest.slices:
        sid = item.slice_id
        matrix = matrices[sid]
        force = vectors[sid]
        contribution = tuple(sum(matrix[row][column] * force[row] for row in range(3)) for column in range(ndof))
        contributions[sid] = contribution
        for column, value in enumerate(contribution):
            generalized[column] += value
        source = force_by_slice_id[sid]
        if isinstance(source, LoadRecord):
            validate_load_record(source, manifest)
            audits[sid] = {
                "s_ref_m": item.s_ref_m,
                "slice_length_m": item.slice_length_m,
                "openfoam_force_N": list(source.openfoam_force_N),
                "force_2d_Npm": list(source.force_2d_Npm),
                "force_N": list(source.force_N),
                "force_local_N": list(source.force_local_N),
            }
        else:
            audits[sid] = {
                "s_ref_m": item.s_ref_m,
                "slice_length_m": item.slice_length_m,
                "force_N": list(force),
            }
    work = None
    if delta_q is not None:
        dq = tuple(_finite_float(value, "delta_q") for value in delta_q)
        if len(dq) != ndof:
            raise MappingError("delta_q length does not match H")
        slice_work = sum(sum(vectors[sid][row] * sum(matrices[sid][row][j] * dq[j] for j in range(ndof)) for row in range(3)) for sid in expected_ids)
        generalized_work = sum(dq[j] * generalized[j] for j in range(ndof))
        error_abs = abs(slice_work - generalized_work)
        error_rel = error_abs / max(1.0, abs(slice_work), abs(generalized_work))
        work = VirtualWorkAudit(
            W_slice_J=slice_work,
            W_generalized_J=generalized_work,
            error_abs_J=error_abs,
            error_rel=error_rel,
            random_seed=random_seed,
            slice_count=len(expected_ids),
            structure_dof_count=ndof,
            slices=tuple({"slice_id": item.slice_id, "s_ref_m": item.s_ref_m, "slice_length_m": item.slice_length_m} for item in manifest.slices),
        )
    return GeneralizedForceResult(tuple(generalized), contributions, audits, work)


def assert_virtual_work(audit: VirtualWorkAudit, tolerance: float = VIRTUAL_WORK_TOLERANCE) -> None:
    if audit.error_rel > tolerance:
        raise VirtualWorkError(f"virtual-work relative error {audit.error_rel} exceeds {tolerance}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
