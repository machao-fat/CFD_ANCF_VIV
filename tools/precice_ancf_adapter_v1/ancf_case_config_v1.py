"""Versioned, paper-independent ANCF case configuration.

This module is intentionally independent of the live preCICE runtime.  It
validates configuration/state identity and constructs the existing
``KernelModel``; it does not add physics or a second section-property model.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from .ancf_kinematics_v1 import NODE_DOF_ORDER


try:
    from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
        BASE_LOAD_SOURCE_CALLER,
        BASE_LOAD_SOURCE_MODEL_STATIC,
        SECTION_PROPERTY_MODE_EXPLICIT,
        SECTION_PROPERTY_MODE_LEGACY,
        KernelModel,
    )
    from coupling.multi_slice_mapping.mapping import SliceDefinition, SliceManifest
except ModuleNotFoundError:  # pragma: no cover - supports direct script imports
    import sys

    _ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_ROOT / "src"))
    from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # type: ignore
        BASE_LOAD_SOURCE_CALLER,
        BASE_LOAD_SOURCE_MODEL_STATIC,
        SECTION_PROPERTY_MODE_EXPLICIT,
        SECTION_PROPERTY_MODE_LEGACY,
        KernelModel,
    )
    from coupling.multi_slice_mapping.mapping import SliceDefinition, SliceManifest  # type: ignore


SCHEMA_VERSION = 1
SECTION_MODES = ("legacy_physical", "explicit")
BASE_LOAD_SOURCES = ("caller_supplied", "model_static")
STATE_KINDS = ("fresh", "prestressed_start", "restart")
PRESTRESS_MODES = ("none", "installed_stretch_target_top_reaction")
FORCE_REPRESENTATION = "integrated_slice_force_N"
MOTION_COMPONENTS = ("x", "y")
PINNED_PRESET = "pinned_position_both_ends"
DOF_ORDER = "per_node[r_x,r_y,r_z,r_sx,r_sy,r_sz]"


class CaseConfigError(ValueError):
    """Configuration or state artifact contract violation."""


def canonical_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CaseConfigError("configuration is not canonicalizable JSON") from exc
    return (text + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise CaseConfigError(f"{name} must be finite numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CaseConfigError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise CaseConfigError(f"{name} must be finite")
    return result


def _positive(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise CaseConfigError(f"{name} must be > 0")
    return result


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CaseConfigError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    result = _nonnegative_int(value, name)
    if result < 1:
        raise CaseConfigError(f"{name} must be >= 1")
    return result


def _vector(value: Any, name: str, length: int | None = None) -> Tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CaseConfigError(f"{name} must be a numeric sequence")
    result = tuple(_finite(item, f"{name}[{i}]") for i, item in enumerate(value))
    if length is not None and len(result) != length:
        raise CaseConfigError(f"{name} must have length {length}")
    if not result:
        raise CaseConfigError(f"{name} must not be empty")
    return result


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CaseConfigError(f"{name} must be an object")
    return value


def _require(mapping: Mapping[str, Any], keys: Sequence[str], name: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise CaseConfigError(f"{name} missing: {', '.join(missing)}")


def _optional_number(mapping: Mapping[str, Any], key: str, default: float, name: str) -> float:
    return _finite(mapping[key], f"{name}.{key}") if key in mapping else default


def _physics_view(value: Any) -> Any:
    """Remove identity/runtime-only data from a configuration before hashing."""

    transient = {"run_id", "output_dir", "runtime_dir", "timestamp", "created_at"}
    if isinstance(value, Mapping):
        return {str(key): _physics_view(item) for key, item in value.items()
                if str(key) not in transient and not str(key).endswith("_sha256")}
    if isinstance(value, (list, tuple)):
        return [_physics_view(item) for item in value]
    return value


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseConfigError(f"cannot read JSON object: {path}") from exc
    return _mapping(value, str(path))


class CaseConfig:
    """Validated generic case configuration."""

    def __init__(self, raw: Mapping[str, Any], base_dir: Path | None = None) -> None:
        self.raw = deepcopy(dict(raw))
        self.base_dir = (base_dir or Path.cwd()).resolve()
        self._validate()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], base_dir: Path | None = None) -> "CaseConfig":
        return cls(value, base_dir)

    @classmethod
    def from_json(cls, path: str | Path) -> "CaseConfig":
        resolved = Path(path).resolve()
        return cls(_read_json(resolved), resolved.parent)

    def _validate(self) -> None:
        root = self.raw
        _require(root, ("schema_version", "case_identity", "model", "section", "environment",
                        "base_load", "boundary", "initial_state", "coupling", "numerics"), "case")
        if root["schema_version"] != SCHEMA_VERSION:
            raise CaseConfigError("unsupported case schema_version")
        identity = _mapping(root["case_identity"], "case_identity")
        if not isinstance(identity.get("case_id"), str) or not identity["case_id"]:
            raise CaseConfigError("case_identity.case_id must be non-empty")
        model = _mapping(root["model"], "model")
        _positive(model.get("length_m"), "model.length_m")
        _positive_int(model.get("elements"), "model.elements")
        section = _mapping(root["section"], "section")
        mode = section.get("mode")
        if mode not in SECTION_MODES:
            raise CaseConfigError("section.mode must be legacy_physical or explicit")
        if mode == SECTION_MODES[0]:
            legacy = _mapping(section.get("legacy"), "section.legacy")
            _require(legacy, ("E_Pa", "D_m", "Di_m", "rho_material_kg_m3"), "section.legacy")
            _positive(legacy["E_Pa"], "section.legacy.E_Pa")
            diameter = _positive(legacy["D_m"], "section.legacy.D_m")
            inner = _finite(legacy["Di_m"], "section.legacy.Di_m")
            if inner < 0.0 or inner >= diameter:
                raise CaseConfigError("section.legacy requires 0 <= Di_m < D_m")
            _positive(legacy["rho_material_kg_m3"], "section.legacy.rho_material_kg_m3")
        else:
            explicit = _mapping(section.get("explicit"), "section.explicit")
            _require(explicit, ("EA_N", "EI_Nm2", "mass_per_length_kg_m", "displaced_area_m2"), "section.explicit")
            for key in ("EA_N", "EI_Nm2", "mass_per_length_kg_m", "displaced_area_m2"):
                _positive(explicit[key], f"section.explicit.{key}")
        environment = _mapping(root["environment"], "environment")
        _positive(environment.get("rho_fluid_kg_m3"), "environment.rho_fluid_kg_m3")
        _positive(environment.get("gravity_m_s2"), "environment.gravity_m_s2")
        base = _mapping(root["base_load"], "base_load")
        if base.get("source") not in BASE_LOAD_SOURCES:
            raise CaseConfigError("base_load.source is invalid")
        if base["source"] == BASE_LOAD_SOURCES[0] and "vector" not in base:
            raise CaseConfigError("caller_supplied base_load requires base_load.vector")
        boundary = _mapping(root["boundary"], "boundary")
        if not isinstance(boundary.get("contract_id"), str) or not boundary["contract_id"]:
            raise CaseConfigError("boundary.contract_id must be non-empty")
        if boundary.get("preset") == PINNED_PRESET:
            _vector(boundary.get("bottom_position_m"), "boundary.bottom_position_m", 3)
            _vector(boundary.get("top_position_m"), "boundary.top_position_m", 3)
        else:
            _vector(boundary.get("fixed_dof"), "boundary.fixed_dof")
            _vector(boundary.get("prescribed_values"), "boundary.prescribed_values")
            if len(boundary["fixed_dof"]) != len(boundary["prescribed_values"]):
                raise CaseConfigError("boundary arrays must have equal length")
        initial = _mapping(root["initial_state"], "initial_state")
        if initial.get("kind") not in STATE_KINDS:
            raise CaseConfigError("initial_state.kind is invalid")
        reference = initial.get("reference_geometry", "case_geometry")
        if reference not in ("case_geometry", "file") and not isinstance(reference, Mapping):
            raise CaseConfigError("initial_state.reference_geometry is invalid")
        if reference == "case_geometry" and "reference_positions_m" not in initial:
            raise CaseConfigError("case_geometry requires initial_state.reference_positions_m")
        coupling = _mapping(root["coupling"], "coupling")
        slices = coupling.get("slices")
        if not isinstance(slices, Sequence) or isinstance(slices, (str, bytes)) or not slices:
            raise CaseConfigError("coupling.slices must be a non-empty array")
        expected_ids = list(range(len(slices)))
        ids = []
        previous = -math.inf
        length = _positive(model["length_m"], "model.length_m")
        for index, raw_slice in enumerate(slices):
            item = _mapping(raw_slice, f"coupling.slices[{index}]")
            _require(item, ("slice_id", "s_ref_m", "slice_length_m", "unit_span_m"), f"coupling.slices[{index}]")
            sid = _nonnegative_int(item["slice_id"], f"coupling.slices[{index}].slice_id")
            s = _finite(item["s_ref_m"], f"coupling.slices[{index}].s_ref_m")
            if s < 0.0 or s > length or s <= previous:
                raise CaseConfigError("slice reference positions must be strictly increasing in [0,length]")
            _positive(item["slice_length_m"], f"coupling.slices[{index}].slice_length_m")
            _positive(item["unit_span_m"], f"coupling.slices[{index}].unit_span_m")
            ids.append(sid); previous = s
        if ids != expected_ids:
            raise CaseConfigError("slice_id must be exactly 0..N-1")
        if coupling.get("force_representation") != FORCE_REPRESENTATION:
            raise CaseConfigError("coupling.force_representation must be integrated_slice_force_N")
        components = coupling.get("motion_components", ["x", "y"])
        if tuple(components) != MOTION_COMPONENTS:
            raise CaseConfigError("UNSUPPORTED_MOTION_COMPONENT: V1 supports exactly x,y")
        numerics = _mapping(root["numerics"], "numerics")
        _positive(numerics.get("dt_s"), "numerics.dt_s")
        for key in ("beta", "gamma", "newton_tolerance"):
            _positive(numerics.get(key), f"numerics.{key}")
        for key in ("gauss_order", "mass_gauss_order", "max_newton"):
            _positive_int(numerics.get(key), f"numerics.{key}")
        if numerics["gauss_order"] not in (3, 5) or numerics["mass_gauss_order"] not in (3, 5):
            raise CaseConfigError("gauss_order and mass_gauss_order must be 3 or 5")
        if numerics["max_newton"] > 1000:
            raise CaseConfigError("max_newton exceeds the current worker contract")
        if numerics.get("damping_alpha", 0.0) != 0.0 or numerics.get("damping_beta", 0.0) != 0.0:
            raise CaseConfigError("STRUCTURAL_DAMPING_NOT_SUPPORTED_V1")
        prestress = root.get("prestress", {"mode": "none"})
        prestress = _mapping(prestress, "prestress")
        prestress_mode = prestress.get("mode", "none")
        if prestress_mode not in PRESTRESS_MODES:
            raise CaseConfigError("prestress.mode is invalid")
        if prestress_mode == "installed_stretch_target_top_reaction":
            _positive(prestress.get("target_reaction_N"), "prestress.target_reaction_N")
            axis = _vector(prestress.get("installation_axis"), "prestress.installation_axis", 3)
            if math.sqrt(sum(item * item for item in axis)) <= 0.0:
                raise CaseConfigError("prestress.installation_axis must be nonzero")
            low = _finite(prestress.get("delta_length_low_m"), "prestress.delta_length_low_m")
            high = _finite(prestress.get("delta_length_high_m"), "prestress.delta_length_high_m")
            if low >= high or low <= -length or high <= -length:
                raise CaseConfigError("prestress delta-length bracket is invalid")
            _positive(prestress.get("relative_target_tolerance"), "prestress.relative_target_tolerance")
            _positive_int(prestress.get("max_iterations"), "prestress.max_iterations")
            _positive_int(prestress.get("static_load_steps", 40), "prestress.static_load_steps")

    @property
    def case_id(self) -> str:
        return str(self.raw["case_identity"]["case_id"])

    @property
    def run_id(self) -> str:
        return str(self.raw["case_identity"].get("run_id", self.case_id))

    @property
    def length_m(self) -> float:
        return float(self.raw["model"]["length_m"])

    @property
    def elements(self) -> int:
        return int(self.raw["model"]["elements"])

    @property
    def ndof(self) -> int:
        return 6 * (self.elements + 1)

    @property
    def config_sha256(self) -> str:
        return canonical_sha256(_physics_view(self.raw))

    @property
    def model_identity_sha256(self) -> str:
        fields = {key: self.raw[key] for key in ("model", "section", "environment", "base_load", "boundary")}
        return canonical_sha256(_physics_view(fields))

    def model_identity_sha256_for_boundary(self, fixed_dof: Sequence[int],
                                           prescribed_values: Sequence[float]) -> str:
        fixed = tuple(int(value) for value in fixed_dof)
        prescribed = tuple(_finite(value, f"prescribed_values[{index}]")
                           for index, value in enumerate(prescribed_values))
        if len(fixed) != len(prescribed):
            raise CaseConfigError("resolved boundary arrays must have equal length")
        fields = {key: deepcopy(self.raw[key]) for key in
                  ("model", "section", "environment", "base_load")}
        fields["boundary"] = {
            "contract_id": self.raw["boundary"]["contract_id"],
            "fixed_dof": list(fixed),
            "prescribed_values": list(prescribed),
        }
        return canonical_sha256(_physics_view(fields))

    def prestress_spec(self) -> dict[str, Any]:
        value = dict(_mapping(self.raw.get("prestress", {"mode": "none"}), "prestress"))
        mode = value.get("mode", "none")
        if mode == "none":
            return {"mode": "none"}
        axis = _vector(value["installation_axis"], "prestress.installation_axis", 3)
        magnitude = math.sqrt(sum(item * item for item in axis))
        fixed, prescribed = self.boundary_arrays()
        expected_fixed = (0, 1, 2, 6 * self.elements, 6 * self.elements + 1, 6 * self.elements + 2)
        if tuple(fixed) != expected_fixed:
            raise CaseConfigError("PRESTRESS_BOUNDARY_CONTRACT_UNSUPPORTED_V1")
        return {
            "mode": mode,
            "target_reaction_N": _positive(value["target_reaction_N"], "prestress.target_reaction_N"),
            "installation_axis": tuple(item / magnitude for item in axis),
            "delta_length_low_m": _finite(value["delta_length_low_m"], "prestress.delta_length_low_m"),
            "delta_length_high_m": _finite(value["delta_length_high_m"], "prestress.delta_length_high_m"),
            "relative_target_tolerance": _positive(value["relative_target_tolerance"], "prestress.relative_target_tolerance"),
            "max_iterations": _positive_int(value["max_iterations"], "prestress.max_iterations"),
            "static_load_steps": _positive_int(value.get("static_load_steps", 40), "prestress.static_load_steps"),
            "bottom_position_m": tuple(prescribed[:3]),
            "configured_top_position_m": tuple(prescribed[3:6]),
        }

    def _metadata(self) -> Mapping[str, Any]:
        model = _mapping(self.raw["model"], "model")
        return _mapping(model.get("kernel_metadata", {}), "model.kernel_metadata")

    def _section_values(self) -> tuple[str, dict[str, float]]:
        section = self.raw["section"]
        mode = section["mode"]
        if mode == "legacy_physical":
            values = section["legacy"]
            return mode, {
                "E_Pa": _positive(values["E_Pa"], "section.legacy.E_Pa"),
                "D_m": _positive(values["D_m"], "section.legacy.D_m"),
                "Di_m": _finite(values["Di_m"], "section.legacy.Di_m"),
                "rho_material_kg_m3": _positive(values["rho_material_kg_m3"], "section.legacy.rho_material_kg_m3"),
            }
        values = section["explicit"]
        return mode, {
            "EA_N": _positive(values["EA_N"], "section.explicit.EA_N"),
            "EI_Nm2": _positive(values["EI_Nm2"], "section.explicit.EI_Nm2"),
            "mass_per_length_kg_m": _positive(values["mass_per_length_kg_m"], "section.explicit.mass_per_length_kg_m"),
            "displaced_area_m2": _positive(values["displaced_area_m2"], "section.explicit.displaced_area_m2"),
        }

    def _state_section_identity(self) -> dict[str, Any]:
        mode, values = self._section_values()
        return {
            "section_property_mode": mode,
            "effective_properties": values,
            "identity_sha256": canonical_sha256(_physics_view(self.raw["section"])),
        }

    def _state_environment_identity(self) -> dict[str, Any]:
        environment = self.raw["environment"]
        values = {
            "fluid_density_kg_m3": _positive(environment["rho_fluid_kg_m3"], "environment.rho_fluid_kg_m3"),
            "gravity_m_s2": _positive(environment["gravity_m_s2"], "environment.gravity_m_s2"),
        }
        return {**values, "identity_sha256": canonical_sha256(_physics_view(self.raw["environment"]))}

    def _state_boundary_identity(self) -> dict[str, Any]:
        fixed, prescribed = self.boundary_arrays()
        boundary = self.raw["boundary"]
        values = {
            "contract_id": boundary["contract_id"],
            "fixed_dof": list(fixed),
            "prescribed_values": list(prescribed),
        }
        return {**values, "identity_sha256": canonical_sha256(_physics_view(values))}

    def boundary_arrays(self) -> tuple[tuple[int, ...], tuple[float, ...]]:
        boundary = self.raw["boundary"]
        if boundary.get("preset") == PINNED_PRESET:
            bottom = _vector(boundary["bottom_position_m"], "boundary.bottom_position_m", 3)
            top = _vector(boundary["top_position_m"], "boundary.top_position_m", 3)
            fixed = (0, 1, 2, 6 * self.elements, 6 * self.elements + 1, 6 * self.elements + 2)
            return fixed, bottom + top
        fixed_raw = _vector(boundary["fixed_dof"], "boundary.fixed_dof")
        fixed = tuple(int(value) for value in fixed_raw)
        if any(value != raw for value, raw in zip(fixed, fixed_raw)) or len(set(fixed)) != len(fixed):
            raise CaseConfigError("boundary.fixed_dof must contain unique integer indices")
        if any(value < 0 or value >= self.ndof for value in fixed):
            raise CaseConfigError("boundary.fixed_dof index is outside the model")
        if tuple(sorted(fixed)) != fixed:
            raise CaseConfigError("boundary.fixed_dof must be strictly increasing")
        prescribed = _vector(boundary["prescribed_values"], "boundary.prescribed_values", len(fixed))
        return fixed, prescribed

    def slices(self) -> tuple[SliceDefinition, ...]:
        return tuple(SliceDefinition(int(item["slice_id"]), float(item["s_ref_m"]),
                                     float(item["slice_length_m"]), float(item["unit_span_m"]))
                     for item in self.raw["coupling"]["slices"])

    def slice_manifest(self) -> SliceManifest:
        slices = self.slices()
        return SliceManifest("0.2.1", self.case_id, self.length_m,
                             sum(item.slice_length_m for item in slices), slices)

    def reference_positions(self) -> tuple[tuple[float, float, float], ...]:
        initial = self.raw["initial_state"]
        reference = initial.get("reference_geometry", "case_geometry")
        if reference == "case_geometry":
            values = initial.get("reference_positions_m")
        else:
            ref = reference if isinstance(reference, Mapping) else {"file": reference}
            path = Path(ref.get("file", ""))
            if not path.is_absolute():
                path = self.base_dir / path
            payload = _read_json(path)
            values = payload.get("positions_m")
        if not isinstance(values, Sequence) or len(values) != len(self.slices()):
            raise CaseConfigError("reference positions must match slice count")
        return tuple(_vector(item, f"reference_positions_m[{i}]", 3)  # type: ignore[misc]
                     for i, item in enumerate(values))

    def kernel_model(self, boundary_override: tuple[Sequence[int], Sequence[float]] | None = None) -> KernelModel:
        mode, section = self._section_values()
        meta = self._metadata()
        if mode == "legacy_physical":
            E = section["E_Pa"]; diameter = section["D_m"]; inner = section["Di_m"]
            material_density = section["rho_material_kg_m3"]
        else:
            # These four values are required by the unchanged wire/model ABI as
            # finite metadata. Explicit structural/base-load values below are
            # authoritative and do not derive from these legacy fields.
            E = _positive(meta.get("youngs_modulus_Pa", 2.07e11), "model.kernel_metadata.youngs_modulus_Pa")
            diameter = _positive(meta.get("diameter_m", 0.028), "model.kernel_metadata.diameter_m")
            inner = _finite(meta.get("inner_diameter_m", 0.024), "model.kernel_metadata.inner_diameter_m")
            material_density = _positive(meta.get("material_density", 7850.0), "model.kernel_metadata.material_density")
        if inner < 0.0 or inner >= diameter:
            raise CaseConfigError("kernel metadata requires 0 <= inner_diameter_m < diameter_m")
        boundary_fixed, prescribed = self.boundary_arrays() if boundary_override is None else (
            tuple(int(value) for value in boundary_override[0]),
            tuple(_finite(value, f"resolved prescribed_values[{index}]")
                  for index, value in enumerate(boundary_override[1])))
        if len(boundary_fixed) != len(prescribed):
            raise CaseConfigError("resolved boundary arrays must have equal length")
        numerics = self.raw["numerics"]
        env = self.raw["environment"]
        model = self.raw["model"]
        kwargs: dict[str, Any] = dict(
            length_m=self.length_m, diameter_m=diameter, inner_diameter_m=inner,
            elements=self.elements, slices=len(self.slices()),
            top_tension_N=_optional_number(meta, "top_tension_N", 2000.0, "model.kernel_metadata"),
            youngs_modulus_Pa=E, material_density=material_density,
            fluid_density=_positive(env["rho_fluid_kg_m3"], "environment.rho_fluid_kg_m3"),
            gravity=_positive(env["gravity_m_s2"], "environment.gravity_m_s2"),
            beta=_positive(numerics["beta"], "numerics.beta"),
            gamma=_positive(numerics["gamma"], "numerics.gamma"),
            newton_tolerance=_positive(numerics["newton_tolerance"], "numerics.newton_tolerance"),
            damping_alpha=0.0, damping_beta=0.0,
            gauss_order=_positive_int(numerics["gauss_order"], "numerics.gauss_order"),
            mass_gauss_order=_positive_int(numerics["mass_gauss_order"], "numerics.mass_gauss_order"),
            max_newton=_positive_int(numerics["max_newton"], "numerics.max_newton"),
            slice_positions_m=tuple(item.s_ref_m for item in self.slices()),
            fixed_dof=boundary_fixed, prescribed_values=prescribed,
            boundary_contract_id=str(self.raw["boundary"]["contract_id"]),
            base_load_source=(BASE_LOAD_SOURCE_CALLER if self.raw["base_load"]["source"] == "caller_supplied"
                              else BASE_LOAD_SOURCE_MODEL_STATIC),
        )
        if mode == "legacy_physical":
            kwargs["section_property_mode"] = SECTION_PROPERTY_MODE_LEGACY
        else:
            kwargs.update(
                section_property_mode=SECTION_PROPERTY_MODE_EXPLICIT,
                explicit_EA_N=section["EA_N"], explicit_EI_Nm2=section["EI_Nm2"],
                explicit_mass_per_length_kg_m=section["mass_per_length_kg_m"],
                explicit_displaced_area_m2=section["displaced_area_m2"],
            )
        return KernelModel(**kwargs)

    def base_load_vector(self, state_base_load: Sequence[float] | None = None) -> tuple[float, ...]:
        source = self.raw["base_load"]["source"]
        if source == "model_static":
            return (0.0,) * self.ndof
        values = state_base_load if state_base_load is not None else self.raw["base_load"].get("vector")
        if isinstance(values, Mapping):
            values = values.get("vector")
        return _vector(values, "base_load.vector", self.ndof)

    def _state_path(self) -> Path | None:
        initial = self.raw["initial_state"]
        path_value = initial.get("state_file")
        if path_value is None:
            return None
        path = Path(path_value)
        return path if path.is_absolute() else self.base_dir / path

    def initial_state(self) -> dict[str, Any]:
        initial = self.raw["initial_state"]
        kind = initial["kind"]
        path = self._state_path()
        if path is not None:
            state = dict(_read_json(path))
        else:
            state = dict(initial)
        model = self.kernel_model()
        if path is not None:
            if state.get("schema_version") != 1:
                raise CaseConfigError("STATE_IDENTITY_FAIL: unsupported state schema_version")
            if state.get("dof_order") != DOF_ORDER or state.get("dof_count") not in (None, model.ndof):
                raise CaseConfigError("STATE_IDENTITY_FAIL: DOF ordering/count mismatch")
            if state.get("length_m") is not None and _finite(state["length_m"], "state.length_m") != self.length_m:
                raise CaseConfigError("STATE_IDENTITY_FAIL: reference length mismatch")
            if state.get("elements") is not None and state["elements"] != self.elements:
                raise CaseConfigError("STATE_IDENTITY_FAIL: element count mismatch")
            if state.get("section") is not None and _physics_view(state["section"]) != _physics_view(self._state_section_identity()):
                raise CaseConfigError("STATE_IDENTITY_FAIL: section identity mismatch")
            if state.get("environment") is not None and _physics_view(state["environment"]) != _physics_view(self._state_environment_identity()):
                raise CaseConfigError("STATE_IDENTITY_FAIL: environment identity mismatch")
            state_boundary = state.get("boundary")
            if state_boundary is not None:
                expected_boundary = self._state_boundary_identity()
                boundary_same = _physics_view(state_boundary) == _physics_view(expected_boundary)
                prestressed_resolved = (kind == "prestressed_start" and
                                        state.get("state_kind") == "prestressed_static" and
                                        state.get("source_model_identity_sha256") == self.model_identity_sha256)
                if not boundary_same and not prestressed_resolved:
                    raise CaseConfigError("STATE_IDENTITY_FAIL: boundary identity mismatch")
                if prestressed_resolved:
                    fixed = tuple(int(value) for value in state_boundary.get("fixed_dof", ()))
                    expected_fixed = self.boundary_arrays()[0]
                    if fixed != expected_fixed or state_boundary.get("contract_id") != self.raw["boundary"]["contract_id"]:
                        raise CaseConfigError("STATE_IDENTITY_FAIL: resolved boundary topology mismatch")
            state_base = state.get("base_load")
            if isinstance(state_base, Mapping):
                if state_base.get("source") != self.raw["base_load"]["source"]:
                    raise CaseConfigError("STATE_IDENTITY_FAIL: base-load source mismatch")
                if self.raw["base_load"]["source"] == "caller_supplied" and state_base.get("vector") is not None:
                    expected_base = self.base_load_vector()
                    actual_base = _vector(state_base["vector"], "state.base_load.vector", model.ndof)
                    if actual_base != expected_base:
                        raise CaseConfigError("STATE_IDENTITY_FAIL: caller base-load mismatch")
        required = ("q", "qdot", "qddot")
        _require(state, required, "initial state")
        result = {key: _vector(state[key], key, model.ndof) for key in required}
        if kind == "prestressed_start":
            if path is None:
                raise CaseConfigError("prestressed_start requires state_file")
            if state.get("case_config_sha256") != self.config_sha256:
                raise CaseConfigError("STATE_IDENTITY_FAIL: case_config_sha256 mismatch")
            state_model_identity = state.get("model_identity_sha256")
            if state.get("state_kind") == "prestressed_static":
                if state.get("source_model_identity_sha256") != self.model_identity_sha256:
                    raise CaseConfigError("STATE_IDENTITY_FAIL: source model identity mismatch")
                if state_model_identity != state.get("resolved_static_model_identity_sha256"):
                    raise CaseConfigError("STATE_IDENTITY_FAIL: resolved model identity mismatch")
            elif state_model_identity != self.model_identity_sha256:
                raise CaseConfigError("STATE_IDENTITY_FAIL: model_identity_sha256 mismatch")
            if state.get("state_kind") not in ("prestressed_start", "static_equilibrium", "prestressed_static"):
                raise CaseConfigError("STATE_IDENTITY_FAIL: state is not a prestressed/static artifact")
            result["qdot"] = _vector(state.get("qdot", (0.0,) * model.ndof), "state.qdot", model.ndof)
            result["qddot"] = _vector(state.get("qddot", (0.0,) * model.ndof), "state.qddot", model.ndof)
            result["time_s"] = 0.0; result["global_step"] = 0
            if state.get("boundary") is not None:
                result["boundary_fixed_dof"] = tuple(int(value) for value in state["boundary"]["fixed_dof"])
                result["boundary_prescribed_values"] = _vector(
                    state["boundary"]["prescribed_values"], "state.boundary.prescribed_values")
        elif kind == "restart":
            if path is None:
                raise CaseConfigError("restart requires state_file")
            if state.get("case_config_sha256") != self.config_sha256 or state.get("model_identity_sha256") != self.model_identity_sha256:
                raise CaseConfigError("STATE_IDENTITY_FAIL: restart identity mismatch")
            if state.get("state_kind") != "restart":
                raise CaseConfigError("STATE_IDENTITY_FAIL: state is not a restart artifact")
            result["time_s"] = _finite(state.get("state_time_s"), "state_time_s")
            result["global_step"] = _nonnegative_int(state.get("global_step"), "global_step")
        else:
            result["time_s"] = _finite(state.get("state_time_s", 0.0), "state_time_s")
            result["global_step"] = _nonnegative_int(state.get("global_step", 0), "global_step")
        if self.raw["base_load"]["source"] == "caller_supplied" and "base_load" in state:
            result["base_load"] = self.base_load_vector(state["base_load"])
        else:
            result["base_load"] = self.base_load_vector()
        return result

    def make_state_artifact(self, q: Sequence[float], qdot: Sequence[float], qddot: Sequence[float],
                            time_s: float, global_step: int) -> dict[str, Any]:
        model = self.kernel_model()
        base = self.base_load_vector()
        fixed, prescribed = self.boundary_arrays()
        base_source = self.raw["base_load"]["source"]
        return {
            "schema_version": 1, "state_kind": self.raw["initial_state"]["kind"],
            "q": list(_vector(q, "q", model.ndof)), "qdot": list(_vector(qdot, "qdot", model.ndof)),
            "qddot": list(_vector(qddot, "qddot", model.ndof)), "dof_order": DOF_ORDER,
            "dof_count": model.ndof,
            "length_m": self.length_m, "reference_material_length_m": self.length_m,
            "elements": self.elements, "section": self._state_section_identity(),
            "environment": self._state_environment_identity(),
            "base_load": {"source": base_source, "vector": list(base) if base_source == "caller_supplied" else None},
            "boundary": {"contract_id": self.raw["boundary"]["contract_id"],
                         "fixed_dof": list(fixed), "prescribed_values": list(prescribed),
                         "identity_sha256": self._state_boundary_identity()["identity_sha256"]},
            "state_time_s": _finite(time_s, "time_s"),
            "global_step": _nonnegative_int(global_step, "global_step"),
            "case_config_sha256": self.config_sha256,
            "model_identity_sha256": self.model_identity_sha256,
        }


def load_case_config(path: str | Path) -> CaseConfig:
    return CaseConfig.from_json(path)
