"""The single source of truth for a generic arbitrary-N live coupling case.

The existing ``multi_slice_mapping`` schema remains frozen for historical
file-exchange cases.  This module adds a richer, string-identity manifest for
the new live path and can still lower it to the frozen numeric ANCF manifest
when a worker request needs the existing kernel-side layout.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


class ManifestError(ValueError):
    """A case or slice manifest violates the arbitrary-N contract."""


_SLICE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_MODES = {"LegacyPointLumped", "PiecewiseLinearDistributed"}
_PLACEMENTS = {"explicit", "uniform_centers", "uniform_endpoints"}
_ENDPOINT_POLICIES = {"NearestConstant"}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ManifestError(f"{name} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ManifestError(f"{name} must be finite")
    return result


def _positive(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise ManifestError(f"{name} must be > 0")
    return result


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ManifestError(f"{name} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{name} must be a non-negative integer") from exc
    if result < 0 or result != float(value):
        raise ManifestError(f"{name} must be a non-negative integer")
    return result


def _positive_int(value: Any, name: str) -> int:
    result = _nonnegative_int(value, name)
    if result < 1:
        raise ManifestError(f"{name} must be >= 1")
    return result


def _canonical(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError("manifest is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sequence(value: Any, name: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ManifestError(f"{name} must be an array")
    return list(value)


def _expand(value: Any, count: int, name: str) -> list[float]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [_finite(item, f"{name}[{index}]") for index, item in enumerate(value)]
        if len(values) != count:
            raise ManifestError(f"{name} must contain exactly {count} values")
        return values
    return [_positive(value, name) for _ in range(count)]


def _mode(value: Any) -> str:
    raw = str(value or "LegacyPointLumped").strip().lower()
    aliases = {
        "legacy_point_lumped": "LegacyPointLumped",
        "legacy": "LegacyPointLumped",
        "legacypointlumped": "LegacyPointLumped",
        "piecewise_linear_distributed": "PiecewiseLinearDistributed",
        "piecewiselineardistributed": "PiecewiseLinearDistributed",
        "distributed": "PiecewiseLinearDistributed",
    }
    result = aliases.get(raw, str(value))
    if result not in _MODES:
        raise ManifestError(f"unsupported reconstruction mode: {value}")
    return result


@dataclass(frozen=True)
class OrchestrationSlice:
    """One stable identity row shared by all orchestration layers."""

    slice_id: str
    ordinal: int
    s_ref_m: float
    slice_length_m: float
    unit_span_m: float
    fluid_participant: str
    structure_participant: str
    structure_mesh: str
    fluid_mesh: str
    force_data: str
    motion_data: str
    openfoam_case_id: str
    force_slot: int
    motion_slot: int
    local_flow_config: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.slice_id, str) or not _SLICE_ID.fullmatch(self.slice_id):
            raise ManifestError("slice_id must be a stable identifier")
        if self.ordinal < 0 or self.force_slot < 0 or self.motion_slot < 0:
            raise ManifestError("slice ordinal/slots must be non-negative")
        for name in ("s_ref_m", "slice_length_m", "unit_span_m"):
            value = _finite(getattr(self, name), name)
            if name != "s_ref_m" and value <= 0.0:
                raise ManifestError(f"{name} must be > 0")
        for name in ("fluid_participant", "structure_participant", "structure_mesh",
                     "fluid_mesh", "force_data", "motion_data", "openfoam_case_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ManifestError(f"{name} must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "ordinal": self.ordinal,
            "s_ref_m": self.s_ref_m,
            "slice_length_m": self.slice_length_m,
            "unit_span_m": self.unit_span_m,
            "fluid_participant": self.fluid_participant,
            "structure_participant": self.structure_participant,
            "structure_mesh": self.structure_mesh,
            "fluid_mesh": self.fluid_mesh,
            "force_data": self.force_data,
            "motion_data": self.motion_data,
            "openfoam_case_id": self.openfoam_case_id,
            "force_slot": self.force_slot,
            "motion_slot": self.motion_slot,
            "local_flow_config": self.local_flow_config,
        }


@dataclass(frozen=True)
class SliceManifest:
    schema_version: str
    case_id: str
    reference_length_m: float
    active_start_m: float
    active_end_m: float
    reconstruction_mode: str
    endpoint_policy: str
    structure_participant: str
    slices: tuple[OrchestrationSlice, ...]
    manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "arbitrary-n-live-coupling-v1":
            raise ManifestError("unsupported arbitrary-N manifest schema")
        if not self.case_id:
            raise ManifestError("case_id must be non-empty")
        length = _positive(self.reference_length_m, "reference_length_m")
        start = _finite(self.active_start_m, "active_start_m")
        end = _finite(self.active_end_m, "active_end_m")
        if start < 0.0 or end > length or start >= end:
            raise ManifestError("active interval must satisfy 0 <= start < end <= length")
        if self.reconstruction_mode not in _MODES:
            raise ManifestError("invalid reconstruction_mode")
        if self.endpoint_policy not in _ENDPOINT_POLICIES:
            raise ManifestError("invalid endpoint_policy")
        if not self.structure_participant:
            raise ManifestError("structure_participant must be non-empty")
        items = tuple(self.slices)
        if not items:
            raise ManifestError("manifest must contain at least one slice")
        if [item.ordinal for item in items] != list(range(len(items))):
            raise ManifestError("slice ordinals must be contiguous and manifest ordered")
        ids = [item.slice_id for item in items]
        if len(set(ids)) != len(ids):
            raise ManifestError("duplicate slice_id")
        positions = [item.s_ref_m for item in items]
        if any(value < start or value > end for value in positions):
            raise ManifestError("slice positions must lie in the active interval")
        if any(right <= left for left, right in zip(positions, positions[1:])):
            raise ManifestError("slice positions must be strictly increasing")
        if self.reconstruction_mode == "PiecewiseLinearDistributed" and len(items) < 2:
            raise ManifestError("distributed mode requires Ns >= 2")
        if any(item.structure_participant != self.structure_participant for item in items):
            raise ManifestError("all slices must use the one structure participant")
        if len({item.force_slot for item in items}) != len(items) or len({item.motion_slot for item in items}) != len(items):
            raise ManifestError("force/motion slots must be unique")
        if self.manifest_sha256 is None:
            object.__setattr__(self, "manifest_sha256", _sha256(self.content_dict()))
        elif self.manifest_sha256 != _sha256(self.content_dict()):
            raise ManifestError("manifest_sha256 does not match content")

    def content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "reference_length_m": self.reference_length_m,
            "active_start_m": self.active_start_m,
            "active_end_m": self.active_end_m,
            "reconstruction_mode": self.reconstruction_mode,
            "endpoint_policy": self.endpoint_policy,
            "structure_participant": self.structure_participant,
            "slices": [item.to_dict() for item in self.slices],
        }

    def to_dict(self) -> dict[str, Any]:
        value = self.content_dict()
        value["manifest_sha256"] = self.manifest_sha256
        return value

    @property
    def ns(self) -> int:
        return len(self.slices)

    @property
    def slice_ids(self) -> tuple[str, ...]:
        return tuple(item.slice_id for item in self.slices)

    def by_id(self, slice_id: str) -> OrchestrationSlice:
        for item in self.slices:
            if item.slice_id == slice_id:
                return item
        raise ManifestError(f"unknown slice_id: {slice_id}")

    def lower_to_numeric_manifest(self):
        """Lower to the frozen numeric manifest used by current worker helpers."""

        from ..multi_slice_mapping.mapping import SliceDefinition, SliceManifest as NumericManifest

        numeric = tuple(
            SliceDefinition(index, item.s_ref_m, item.slice_length_m, item.unit_span_m)
            for index, item in enumerate(self.slices)
        )
        return NumericManifest(
            "0.2.1", self.case_id, self.reference_length_m,
            sum(item.slice_length_m for item in self.slices), numeric,
        )


def _raw_root(config: Any) -> Mapping[str, Any]:
    if hasattr(config, "raw"):
        config = config.raw
    if not isinstance(config, Mapping):
        raise ManifestError("case configuration must be a mapping or expose .raw")
    return config


def build_slice_manifest(config: Mapping[str, Any] | Any) -> SliceManifest:
    """Build one manifest from explicit or generated placement configuration.

    Accepted new configuration shape::

        {"case_id": "case", "length_m": 10.0,
         "coupling": {"mode": "PiecewiseLinearDistributed",
                       "placement": "uniform_centers", "count": 5,
                       "active_start_m": 0.0, "active_end_m": 10.0,
                       "unit_span_m": 1.0}}

    The existing CaseConfig shape is accepted as well; its explicit
    ``coupling.slices`` table is converted without changing its semantics.
    """

    root = _raw_root(config)
    model = root.get("model", {}) if isinstance(root.get("model", {}), Mapping) else {}
    length = _positive(root.get("length_m", model.get("length_m")), "length_m")
    case_identity = root.get("case_identity", {})
    if isinstance(case_identity, Mapping):
        default_case_id = case_identity.get("case_id", "")
    else:
        default_case_id = ""
    case_id = str(root.get("case_id", default_case_id))
    if not case_id:
        raise ManifestError("case_id is required")
    coupling = root.get("coupling", {})
    if not isinstance(coupling, Mapping):
        raise ManifestError("coupling must be an object")
    nested = coupling.get("spanwise_load_reconstruction", {})
    if not isinstance(nested, Mapping):
        nested = {}
    raw_mode = coupling.get("mode", coupling.get("reconstruction_mode", nested.get("mode", "LegacyPointLumped")))
    mode = _mode(raw_mode)
    endpoint = str(coupling.get("endpoint_policy", nested.get("endpoint_policy", "NearestConstant")))
    endpoint_alias = {"nearest_constant": "NearestConstant", "nearestconstant": "NearestConstant"}
    endpoint = endpoint_alias.get(endpoint.lower(), endpoint)
    if endpoint not in _ENDPOINT_POLICIES:
        raise ManifestError("endpoint_policy must be NearestConstant")
    if "force_representation" in coupling:
        expected = "integrated_slice_force_N" if mode == "LegacyPointLumped" else "sectional_line_force_Npm"
        if coupling["force_representation"] != expected:
            raise ManifestError("force representation does not match reconstruction mode")

    placement_value = coupling.get("placement", coupling.get("slice_placement"))
    explicit_items = coupling.get("slices")
    if placement_value is None and explicit_items is not None:
        placement = "explicit"
    else:
        placement = str(placement_value or "explicit").lower()
    if placement not in _PLACEMENTS:
        raise ManifestError(f"unsupported placement: {placement}")

    active_start = _finite(coupling.get("active_start_m", nested.get("active_start_m", 0.0)), "active_start_m")
    active_end = _finite(coupling.get("active_end_m", nested.get("active_end_m", length)), "active_end_m")
    if active_start < 0.0 or active_end > length or active_start >= active_end:
        raise ManifestError("invalid active interval")

    if placement == "explicit":
        positions: list[float]
        if explicit_items is not None:
            rows = _sequence(explicit_items, "coupling.slices")
            if not rows:
                raise ManifestError("coupling.slices must not be empty")
            positions = [_finite(row["s_ref_m"], f"coupling.slices[{i}].s_ref_m") for i, row in enumerate(rows)]
            ids = [str(row.get("slice_id", f"slice_{i:04d}")) for i, row in enumerate(rows)]
            lengths_value = [row.get("slice_length_m") for row in rows]
            spans_value = [row.get("unit_span_m") for row in rows]
            if any(value is None for value in lengths_value + spans_value):
                raise ManifestError("explicit slices require slice_length_m and unit_span_m")
            lengths = [_positive(value, f"coupling.slices[{i}].slice_length_m") for i, value in enumerate(lengths_value)]
            spans = [_positive(value, f"coupling.slices[{i}].unit_span_m") for i, value in enumerate(spans_value)]
            local_flow = [row.get("local_flow_config") for row in rows]
        else:
            positions = [_finite(value, f"positions_m[{i}]") for i, value in enumerate(_sequence(coupling.get("positions_m"), "positions_m"))]
            count = len(positions)
            ids = [str(value) for value in coupling.get("slice_ids", [f"slice_{i:04d}" for i in range(count)])]
            lengths = _expand(coupling.get("slice_length_m", coupling.get("slice_lengths_m")), count, "slice_length_m")
            spans = _expand(coupling.get("unit_span_m", coupling.get("unit_spans_m")), count, "unit_span_m")
            local_flow = list(coupling.get("local_flow_config", [None] * count))
    else:
        count = _positive_int(coupling.get("count"), "count")
        if mode == "PiecewiseLinearDistributed" and count < 2:
            raise ManifestError("distributed placement requires count >= 2")
        delta = (active_end - active_start) / count
        if placement == "uniform_centers":
            positions = [active_start + (index + 0.5) * delta for index in range(count)]
        else:
            if count < 2:
                raise ManifestError("uniform_endpoints requires count >= 2")
            positions = [active_start + index * (active_end - active_start) / (count - 1) for index in range(count)]
        ids = [f"slice_{index:04d}" for index in range(count)]
        lengths_value = coupling.get("slice_length_m", coupling.get("slice_lengths_m", delta))
        spans_value = coupling.get("unit_span_m", coupling.get("unit_spans_m"))
        if spans_value is None:
            raise ManifestError("generated placement requires unit_span_m or unit_spans_m")
        lengths = _expand(lengths_value, count, "slice_length_m")
        spans = _expand(spans_value, count, "unit_span_m")
        local_flow = list(coupling.get("local_flow_config", [None] * count))

    if len(local_flow) != len(positions):
        raise ManifestError("local_flow_config must match slice count")
    if len(set(ids)) != len(ids) or any(not _SLICE_ID.fullmatch(value) for value in ids):
        raise ManifestError("slice IDs must be unique stable identifiers")
    if mode == "PiecewiseLinearDistributed" and len(positions) < 2:
        raise ManifestError("distributed mode requires Ns >= 2")
    if any(position < active_start or position > active_end for position in positions):
        raise ManifestError("slice positions must lie in active interval")
    if any(right <= left for left, right in zip(positions, positions[1:])):
        raise ManifestError("slice positions must be strictly increasing")

    names = root.get("interfaces", {})
    if not isinstance(names, Mapping):
        names = {}
    structure = str(names.get("structure_participant", root.get("structure_participant", "StructureCoordinator")))
    fluid_prefix = str(names.get("fluid_participant_prefix", "Fluid_"))
    structure_mesh_prefix = str(names.get("structure_mesh_prefix", "Structure-Mesh-"))
    fluid_mesh_prefix = str(names.get("fluid_mesh_prefix", "Fluid-Mesh-"))
    openfoam_prefix = str(names.get("openfoam_case_prefix", case_id + "_"))
    force_data = str(names.get("force_data", "Force"))
    motion_data = str(names.get("motion_data", "Displacement"))
    slices = tuple(
        OrchestrationSlice(
            slice_id=ids[index], ordinal=index, s_ref_m=positions[index],
            slice_length_m=lengths[index], unit_span_m=spans[index],
            fluid_participant=f"{fluid_prefix}{ids[index]}",
            structure_participant=structure,
            structure_mesh=f"{structure_mesh_prefix}{ids[index]}",
            fluid_mesh=f"{fluid_mesh_prefix}{ids[index]}",
            force_data=force_data, motion_data=motion_data,
            openfoam_case_id=f"{openfoam_prefix}{ids[index]}",
            force_slot=index, motion_slot=index,
            local_flow_config=None if local_flow[index] is None else str(local_flow[index]),
        ) for index in range(len(positions))
    )
    return SliceManifest(
        schema_version="arbitrary-n-live-coupling-v1", case_id=case_id,
        reference_length_m=length, active_start_m=active_start, active_end_m=active_end,
        reconstruction_mode=mode, endpoint_policy=endpoint,
        structure_participant=structure, slices=slices,
    )
