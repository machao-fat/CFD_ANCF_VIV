from __future__ import annotations

import hashlib
import math
from numbers import Real
import struct
from dataclasses import dataclass
from typing import BinaryIO, Sequence

from .protocol import (FrameError, HEADER, MAGIC, SCHEMA_VERSION,
                       PROTOCOL_VERSION, canonical_integer_tick, canonical_tick_delta)


MESSAGE_KERNEL_STEP_REQUEST = 5
MESSAGE_KERNEL_STEP_RESPONSE = 6
ID_RUN = 64
ID_CASE = 64
ID_ENDPOINT = 32
REQUEST_PRODUCER = "python_scheduler"
REQUEST_CONSUMER = "cpp_ancf_kernel_worker"
MAX_NDOF = 2048
MAX_NEWTON = 1000
EXTENDED_LAYOUT_MARKER = 0x314C5845  # "EXL1", little-endian
SECTION_PROPERTY_EXTENSION_MARKER = 0x31585053  # "SPX1", little-endian
SECTION_PROPERTY_EXTENSION_VERSION = 1
SECTION_PROPERTY_MODE_LEGACY = "legacy_physical"
SECTION_PROPERTY_MODE_EXPLICIT = "explicit"
_SECTION_PROPERTY_MODE_EXPLICIT_WIRE = 1
BASE_LOAD_SOURCE_CALLER = "caller_supplied"
BASE_LOAD_SOURCE_MODEL_STATIC = "model_static"
BASE_LOAD_SOURCE_EXTENSION_MARKER = 0x31534C42  # "BLS1", little-endian
BASE_LOAD_SOURCE_EXTENSION_VERSION = 1
_BASE_LOAD_SOURCE_CALLER_WIRE = 0
_BASE_LOAD_SOURCE_MODEL_STATIC_WIRE = 1
DAMPING_EXTENSION_MARKER = 0x31504D44  # "DMP1", little-endian
DAMPING_EXTENSION_VERSION = 1
DAMPING_MODE_RAYLEIGH = 1
DAMPING_REFERENCE_DYNAMIC_INITIAL = 1
DAMPING_PSD_POLICY_ID = 1
SPANWISE_LOAD_EXTENSION_MARKER = 0x31444C53  # "SLD1", little-endian
SPANWISE_LOAD_EXTENSION_VERSION = 1
_SPANWISE_LOAD_MODE_PIECEWISE_LINEAR_WIRE = 1
SPANWISE_ENDPOINT_NEAREST_CONSTANT = 1
SPANWISE_HYDRODYNAMIC_EXTENSION_MARKER = 0x314D4853  # "SHM1", little-endian
SPANWISE_HYDRODYNAMIC_EXTENSION_VERSION = 1
MAX_SPANWISE_HYDRODYNAMIC_REGIONS = 10_000
SPANWISE_LOAD_MODE_LEGACY = "legacy_point_lumped"
SPANWISE_LOAD_MODE_PIECEWISE_LINEAR = "piecewise_linear_distributed"
SPANWISE_ENDPOINT_POLICY_NEAREST_CONSTANT = "nearest_constant"
_DAMPING_TAG = b"ancf-damping-v1\0"
_DAMPING_REFERENCE_TAG = b"ancf-damping-ref-v1\0"
DOF_ORDER_IDENTITY = "per_node[r_x,r_y,r_z,r_sx,r_sy,r_sz]"
CANONICAL_BOUNDARY_CONTRACT_ID = "ancf_v1_bottom_top_xy_zero"

# v1 is a positional response schema without per-field wire labels. Preserve
# the historical MATLAB golden-record meaning explicitly: both force slots
# contain total Qext (base load plus mapped slice force). A CFD-only force
# field requires a versioned schema migration.
RESPONSE_FIELD_SEMANTICS = {
    "external_force": "total_Qext",
    "generalized_force": "total_Qext_alias",
    "internal_force": "Qint_at_corrected_state",
    "predictor": "Newmark_position_predictor",
    "corrector": "corrected_q",
}

_PREFIX = struct.Struct("<IIIiiQddiiiiiQQ")
_MODEL = struct.Struct("<13dii")
_SECTION_PROPERTY_EXTENSION = struct.Struct("<III4d")
_SPANWISE_HYDRODYNAMIC_EXTENSION_HEADER = struct.Struct("<III")
_SPANWISE_HYDRODYNAMIC_REGION = struct.Struct("<8d")
_BOUNDARY_ID = 64
_RESPONSE_PREFIX = struct.Struct("<IIIiiQdiiidQQI")


def damping_identity_sha256(alpha_mass_per_s: float, beta_stiffness_s: float,
                            *, mode: int = DAMPING_MODE_RAYLEIGH,
                            reference_kind: int = DAMPING_REFERENCE_DYNAMIC_INITIAL,
                            psd_policy_id: int = DAMPING_PSD_POLICY_ID) -> str:
    """Hash the exact binary DMP1 damping semantics."""
    if not all(math.isfinite(float(value)) for value in (alpha_mass_per_s, beta_stiffness_s)):
        raise FrameError("damping coefficients must be finite")
    payload = (_DAMPING_TAG + struct.pack("<IddII", int(mode), float(alpha_mass_per_s),
                                           float(beta_stiffness_s), int(reference_kind),
                                           int(psd_policy_id)))
    return hashlib.sha256(payload).hexdigest()


def damping_reference_state_sha256(q_ref: Sequence[float], model_identity_sha256: str,
                                   *, reference_kind: int = DAMPING_REFERENCE_DYNAMIC_INITIAL) -> str:
    """Hash q_ref plus the structural identity used to construct K_ref."""
    values = _finite_vector(q_ref, "damping.q_ref")
    if len(model_identity_sha256) != 64:
        raise FrameError("damping model identity must be a SHA-256 hex string")
    try:
        model_digest = bytes.fromhex(model_identity_sha256)
    except ValueError as exc:
        raise FrameError("damping model identity is not SHA-256 hex") from exc
    payload = (_DAMPING_REFERENCE_TAG + model_digest + DOF_ORDER_IDENTITY.encode("ascii") +
               struct.pack("<II", int(reference_kind), len(values)) +
               struct.pack("<" + "d" * len(values), *values))
    return hashlib.sha256(payload).hexdigest()


def _finite_vector(values: Sequence[float], name: str) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise FrameError(f"{name} is not a numeric sequence")
    try:
        result_values = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise FrameError(f"{name} contains a non-numeric value")
            result_values.append(float(value))
    except TypeError as exc:
        raise FrameError(f"{name} is not a numeric sequence") from exc
    result = tuple(result_values)
    if not result or any(not math.isfinite(value) for value in result):
        raise FrameError(f"{name} is empty or contains NaN/Inf")
    return result


def _fixed(value: str, size: int, name: str) -> bytes:
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 for char in value):
        raise FrameError(f"{name} is missing or contains a control character")
    raw = value.encode("utf-8")
    if b"\0" in raw or len(raw) >= size:
        raise FrameError(f"{name} is missing or too long")
    return raw + b"\0" * (size - len(raw))


def _bounded_int(value: int, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise FrameError(f"{name} is outside its wire range")
    return value


@dataclass(frozen=True)
class SpanwiseHydrodynamicRegion:
    """Resolved global-coordinate regional hydro coefficients for SHM1."""

    s_min_m: float
    s_max_m: float
    added_mass_per_length_kg_m: tuple[float, float, float]
    linear_damping_per_length_Ns_m2: tuple[float, float, float]

    def wire_values(self) -> tuple[float, ...]:
        return (float(self.s_min_m), float(self.s_max_m),
                *(float(value) for value in self.added_mass_per_length_kg_m),
                *(float(value) for value in self.linear_damping_per_length_Ns_m2))


def _validate_spanwise_hydrodynamic_regions(
        regions: Sequence[SpanwiseHydrodynamicRegion], length_m: float) -> None:
    if isinstance(regions, (str, bytes)):
        raise FrameError("hydrodynamic_regions is not a sequence")
    if len(regions) > MAX_SPANWISE_HYDRODYNAMIC_REGIONS:
        raise FrameError("hydrodynamic_regions exceeds its wire bound")
    previous_start: float | None = None
    previous_end: float | None = None
    for index, region in enumerate(regions):
        if not isinstance(region, SpanwiseHydrodynamicRegion):
            raise FrameError(f"hydrodynamic_regions[{index}] has an invalid type")
        values = region.wire_values()
        if any(not math.isfinite(value) for value in values):
            raise FrameError(f"hydrodynamic_regions[{index}] contains NaN/Inf")
        if region.s_min_m < 0.0 or region.s_min_m >= region.s_max_m or region.s_max_m > length_m:
            raise FrameError(f"hydrodynamic_regions[{index}] interval is invalid")
        if any(value < 0.0 for value in values[2:]):
            raise FrameError(f"hydrodynamic_regions[{index}] coefficient is negative")
        if (previous_start is not None and
                (region.s_min_m < previous_start or region.s_min_m < previous_end)):
            raise FrameError("hydrodynamic_regions are unsorted or overlap")
        previous_start, previous_end = region.s_min_m, region.s_max_m


@dataclass(frozen=True)
class KernelModel:
    length_m: float = 100.0
    diameter_m: float = 0.028
    inner_diameter_m: float = 0.024
    elements: int = 10
    slices: int = 11
    top_tension_N: float = 2000.0
    youngs_modulus_Pa: float = 2.07e11
    material_density: float = 7850.0
    fluid_density: float = 1025.0
    gravity: float = 9.81
    beta: float = 0.25
    gamma: float = 0.5
    newton_tolerance: float = 1e-8
    damping_alpha: float = 0.0
    damping_beta: float = 0.0
    gauss_order: int = 3
    mass_gauss_order: int = 5
    max_newton: int = 40
    slice_positions_m: tuple[float, ...] = ()
    fixed_dof: tuple[int, ...] = ()
    prescribed_values: tuple[float, ...] = ()
    boundary_contract_id: str = "ancf_v1_bottom_top_xy_zero"
    # Kept explicit in the model object even though the v1 wire layout
    # intentionally requires both owned components to be enabled.
    include_gravity: bool = True
    include_buoyancy: bool = True
    # Appended fields preserve source compatibility for existing positional
    # callers.  None means that no explicit section value was supplied.
    section_property_mode: str = SECTION_PROPERTY_MODE_LEGACY
    explicit_EA_N: float | None = None
    explicit_EI_Nm2: float | None = None
    explicit_mass_per_length_kg_m: float | None = None
    explicit_displaced_area_m2: float | None = None
    # Missing means the historical caller-supplied base-load path.
    base_load_source: str = BASE_LOAD_SOURCE_CALLER
    # Additive spanwise line-load contract.  The legacy defaults intentionally
    # emit no SLD1 trailer and preserve the historical model bytes.
    spanwise_load_reconstruction: str = SPANWISE_LOAD_MODE_LEGACY
    spanwise_active_s_min_m: float = 0.0
    spanwise_active_s_max_m: float | None = None
    spanwise_endpoint_policy: str = SPANWISE_ENDPOINT_POLICY_NEAREST_CONSTANT
    # Empty remains byte-identical to the historical model layout: SHM1 is
    # emitted only for a non-empty, validated regional contract.
    hydrodynamic_regions: tuple[SpanwiseHydrodynamicRegion, ...] = ()

    @property
    def ndof(self) -> int:
        if isinstance(self.elements, bool) or not isinstance(self.elements, int):
            raise FrameError("kernel elements is not an integer")
        return 6 * (self.elements + 1)

    def validate(self, dt_s: float) -> None:
        mode = self.section_property_mode
        if mode not in (SECTION_PROPERTY_MODE_LEGACY, SECTION_PROPERTY_MODE_EXPLICIT):
            raise FrameError("kernel section_property_mode is unknown")
        if self.base_load_source not in (BASE_LOAD_SOURCE_CALLER, BASE_LOAD_SOURCE_MODEL_STATIC):
            raise FrameError("kernel base_load_source is unknown")
        if self.spanwise_load_reconstruction not in (
                SPANWISE_LOAD_MODE_LEGACY, SPANWISE_LOAD_MODE_PIECEWISE_LINEAR):
            raise FrameError("kernel spanwise_load_reconstruction is unknown")
        if self.spanwise_endpoint_policy != SPANWISE_ENDPOINT_POLICY_NEAREST_CONSTANT:
            raise FrameError("kernel spanwise endpoint policy is unknown")
        explicit_values = (
            self.explicit_EA_N,
            self.explicit_EI_Nm2,
            self.explicit_mass_per_length_kg_m,
            self.explicit_displaced_area_m2,
        )
        if mode == SECTION_PROPERTY_MODE_LEGACY:
            if any(value is not None for value in explicit_values):
                raise FrameError("explicit section properties require explicit section_property_mode")
        else:
            for name, value in (
                ("explicit_EA_N", self.explicit_EA_N),
                ("explicit_EI_Nm2", self.explicit_EI_Nm2),
                ("explicit_mass_per_length_kg_m", self.explicit_mass_per_length_kg_m),
                ("explicit_displaced_area_m2", self.explicit_displaced_area_m2),
            ):
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise FrameError(f"kernel model {name} is missing or not numeric")
                value = float(value)
                if not math.isfinite(value) or value <= 0.0:
                    raise FrameError(f"kernel model {name} must be finite and positive")
        for name, value in (("elements", self.elements), ("slices", self.slices),
                            ("gauss_order", self.gauss_order), ("mass_gauss_order", self.mass_gauss_order),
                            ("max_newton", self.max_newton)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise FrameError(f"kernel model {name} is not an integer")
        if (self.elements < 1 or self.elements > 10000 or self.slices < 1 or
                self.slices > 1000 or self.ndof > MAX_NDOF or self.gauss_order not in (3, 5) or
                self.mass_gauss_order not in (3, 5)):
            raise FrameError("kernel model dimensions or quadrature order are invalid")
        if self.max_newton <= 0 or self.max_newton > MAX_NEWTON or self.newton_tolerance <= 0.0:
            raise FrameError("kernel Newton contract is invalid")
        for name, value in (("damping_alpha", self.damping_alpha), ("damping_beta", self.damping_beta)):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                raise FrameError(f"kernel model {name} is NaN/Inf or not numeric")
            if float(value) < 0.0:
                raise FrameError(f"kernel model {name} must be non-negative")
        if not isinstance(self.include_gravity, bool) or not isinstance(self.include_buoyancy, bool):
            raise FrameError("kernel physics switches must be boolean")
        # The v1 wire model does not carry these switches.  Accepting false
        # here would silently make the C++ ownership worker use different
        # physics from the request, so reject the unrepresentable contract.
        if not self.include_gravity or not self.include_buoyancy:
            raise FrameError("kernel v1 wire contract requires gravity and buoyancy enabled")
        for name, value in (("length_m", self.length_m), ("diameter_m", self.diameter_m),
                            ("inner_diameter_m", self.inner_diameter_m), ("youngs_modulus_Pa", self.youngs_modulus_Pa),
                            ("material_density", self.material_density), ("fluid_density", self.fluid_density),
                            ("gravity", self.gravity), ("top_tension_N", self.top_tension_N),
                            ("beta", self.beta), ("gamma", self.gamma),
                            ("newton_tolerance", self.newton_tolerance), ("dt_s", dt_s)):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise FrameError(f"kernel model {name} is not numeric")
            if not math.isfinite(float(value)):
                raise FrameError(f"kernel model {name} is NaN/Inf")
        if (self.length_m <= 0.0 or self.diameter_m <= 0.0 or
                self.diameter_m <= self.inner_diameter_m or self.inner_diameter_m < 0.0 or dt_s <= 0.0):
            raise FrameError("kernel geometry or time step is invalid")
        _validate_spanwise_hydrodynamic_regions(self.hydrodynamic_regions, float(self.length_m))
        if isinstance(self.slice_positions_m, (str, bytes)):
            raise FrameError("kernel slice positions are not numeric")
        if self.slice_positions_m and (len(self.slice_positions_m) != self.slices or
                                       any(isinstance(x, bool) or not isinstance(x, Real) or
                                           not math.isfinite(float(x)) or x < 0.0 or x > self.length_m
                                           for x in self.slice_positions_m) or
                                       any(self.slice_positions_m[i] <= self.slice_positions_m[i - 1]
                                           for i in range(1, len(self.slice_positions_m)))):
            raise FrameError("kernel slice positions are invalid")
        if self.spanwise_load_reconstruction == SPANWISE_LOAD_MODE_PIECEWISE_LINEAR:
            if (self.slices < 2 or not self.slice_positions_m or
                    self.spanwise_active_s_max_m is None or
                    isinstance(self.spanwise_active_s_max_m, bool) or
                    not isinstance(self.spanwise_active_s_max_m, Real) or
                    not isinstance(self.spanwise_active_s_min_m, Real) or
                    not math.isfinite(float(self.spanwise_active_s_min_m)) or
                    not math.isfinite(float(self.spanwise_active_s_max_m)) or
                    self.spanwise_active_s_min_m < 0.0 or
                    self.spanwise_active_s_max_m > self.length_m or
                    self.spanwise_active_s_min_m > self.spanwise_active_s_max_m or
                    self.spanwise_active_s_min_m > self.slice_positions_m[0] or
                    self.slice_positions_m[-1] > self.spanwise_active_s_max_m):
                raise FrameError("kernel distributed-load active region is invalid")
        fixed = self.fixed_dof or (0, 1, 2, 6 * self.elements, 6 * self.elements + 1)
        prescribed = self.prescribed_values or (0.0,) * len(fixed)
        if (len(fixed) != len(prescribed) or not fixed or
                any(isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= self.ndof
                    for index in fixed) or
                any(fixed[index] <= fixed[index - 1] for index in range(1, len(fixed))) or
                any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value))
                    for value in prescribed)):
            raise FrameError("kernel boundary contract is invalid")
        canonical_fixed = (0, 1, 2, 6 * self.elements, 6 * self.elements + 1)
        if self.boundary_contract_id == CANONICAL_BOUNDARY_CONTRACT_ID and (
                tuple(fixed) != canonical_fixed or any(float(value) != 0.0 for value in prescribed)):
            raise FrameError("canonical boundary contract does not match fixed DOF or prescribed values")
        _fixed(self.boundary_contract_id, _BOUNDARY_ID, "boundary_contract_id")

    def bytes(self) -> bytes:
        self.validate(1.0)
        positions = self.slice_positions_m or tuple(self.length_m * k / max(1, self.slices - 1) for k in range(self.slices))
        fixed = self.fixed_dof or (0, 1, 2, 6 * self.elements, 6 * self.elements + 1)
        prescribed = self.prescribed_values or (0.0,) * len(fixed)
        boundary = _fixed(self.boundary_contract_id, _BOUNDARY_ID, "boundary_contract_id")
        base = _MODEL.pack(self.length_m, self.diameter_m, self.inner_diameter_m,
                           self.top_tension_N, self.youngs_modulus_Pa, self.material_density,
                           self.fluid_density, self.gravity, self.beta, self.gamma,
                           self.newton_tolerance, self.damping_alpha, self.damping_beta,
                           self.gauss_order, self.max_newton)
        positions_bytes = struct.pack("<" + "d" * self.slices, *positions)
        has_custom_boundary = bool(self.fixed_dof or self.prescribed_values or self.mass_gauss_order != 5 or
                                   self.boundary_contract_id != CANONICAL_BOUNDARY_CONTRACT_ID)
        if has_custom_boundary:
            model_bytes = base + struct.pack("<Iii", EXTENDED_LAYOUT_MARKER, self.mass_gauss_order, len(fixed)) + boundary + \
                struct.pack("<" + "i" * len(fixed), *fixed) + struct.pack("<" + "d" * len(prescribed), *prescribed) + \
                positions_bytes
        else:
            model_bytes = base + positions_bytes
        if self.section_property_mode == SECTION_PROPERTY_MODE_EXPLICIT:
            model_bytes += _SECTION_PROPERTY_EXTENSION.pack(
                SECTION_PROPERTY_EXTENSION_MARKER,
                SECTION_PROPERTY_EXTENSION_VERSION,
                _SECTION_PROPERTY_MODE_EXPLICIT_WIRE,
                float(self.explicit_EA_N),
                float(self.explicit_EI_Nm2),
                float(self.explicit_mass_per_length_kg_m),
                float(self.explicit_displaced_area_m2),
            )
        if self.base_load_source == BASE_LOAD_SOURCE_MODEL_STATIC:
            model_bytes += struct.pack(
                "<III",
                BASE_LOAD_SOURCE_EXTENSION_MARKER,
                BASE_LOAD_SOURCE_EXTENSION_VERSION,
                _BASE_LOAD_SOURCE_MODEL_STATIC_WIRE,
            )
        if self.spanwise_load_reconstruction == SPANWISE_LOAD_MODE_PIECEWISE_LINEAR:
            model_bytes += struct.pack(
                "<IIIIdd",
                SPANWISE_LOAD_EXTENSION_MARKER,
                SPANWISE_LOAD_EXTENSION_VERSION,
                _SPANWISE_LOAD_MODE_PIECEWISE_LINEAR_WIRE,
                SPANWISE_ENDPOINT_NEAREST_CONSTANT,
                float(self.spanwise_active_s_min_m),
                float(self.spanwise_active_s_max_m),
            )
        if self.hydrodynamic_regions:
            model_bytes += _SPANWISE_HYDRODYNAMIC_EXTENSION_HEADER.pack(
                SPANWISE_HYDRODYNAMIC_EXTENSION_MARKER,
                SPANWISE_HYDRODYNAMIC_EXTENSION_VERSION,
                len(self.hydrodynamic_regions),
            )
            for region in self.hydrodynamic_regions:
                model_bytes += _SPANWISE_HYDRODYNAMIC_REGION.pack(*region.wire_values())
        return model_bytes


@dataclass(frozen=True)
class KernelStepRequest:
    sequence: int
    global_step: int
    case_local_bridge_step: int
    integer_tick: int
    time_s: float
    dt_s: float
    request_id: int
    transaction_id: int
    run_id: str
    case_id: str
    model: KernelModel
    q: tuple[float, ...]
    qdot: tuple[float, ...]
    qddot: tuple[float, ...]
    base_load: tuple[float, ...]
    slice_force: tuple[float, ...]
    # Optional source-state mass matrix, flattened row-major.  When omitted,
    # the worker uses its canonical reconstructed matrix for legacy requests.
    mass_matrix: tuple[float, ...] = ()
    producer: str = "python_scheduler"
    consumer: str = "cpp_ancf_kernel_worker"
    damping_mode: str = "none"
    damping_reference_state: str = "dynamic_initial"
    damping_identity_sha256: str = ""
    damping_reference_state_identity_sha256: str = ""
    damping_model_identity_sha256: str = ""
    damping_q_ref: tuple[float, ...] = ()
    damping_psd_policy_id: int = DAMPING_PSD_POLICY_ID
    spanwise_line_force_Npm: tuple[float, ...] = ()

    def payload(self) -> bytes:
        self.model.validate(self.dt_s)
        if self.producer != REQUEST_PRODUCER or self.consumer != REQUEST_CONSUMER:
            raise FrameError("kernel request producer/consumer endpoint mismatch")
        n = self.model.ndof
        q = _finite_vector(self.q, "q"); qdot = _finite_vector(self.qdot, "qdot")
        qddot = _finite_vector(self.qddot, "qddot"); base = _finite_vector(self.base_load, "base_load")
        distributed = self.model.spanwise_load_reconstruction == SPANWISE_LOAD_MODE_PIECEWISE_LINEAR
        if distributed:
            if self.slice_force:
                raise FrameError("distributed requests must not carry legacy slice_force")
            force = _finite_vector(self.spanwise_line_force_Npm, "spanwise_line_force_Npm")
        else:
            force = _finite_vector(self.slice_force, "slice_force")
            if self.spanwise_line_force_Npm:
                raise FrameError("legacy requests must not carry spanwise_line_force_Npm")
        if isinstance(self.mass_matrix, (str, bytes)):
            raise FrameError("mass_matrix is not a numeric sequence")
        try:
            raw_mass = tuple(self.mass_matrix)
        except TypeError as exc:
            raise FrameError("mass_matrix is not a numeric sequence") from exc
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in raw_mass):
            raise FrameError("mass_matrix contains a non-numeric value")
        try:
            mass = tuple(float(value) for value in raw_mass)
        except (TypeError, ValueError, OverflowError) as exc:
            raise FrameError("mass_matrix is not a numeric sequence") from exc
        if mass and len(mass) != n * n:
            raise FrameError("mass_matrix dimension is inconsistent with model")
        if any(not math.isfinite(value) for value in mass):
            raise FrameError("mass_matrix contains NaN/Inf")
        # MATLAB's exported mass contract is explicitly symmetrized before it
        # reaches the worker. Reject a mutated asymmetric matrix instead of
        # silently changing the matrix used by Newton after hashing.
        if mass and any(mass[row * n + col] != mass[col * n + row]
                        for row in range(n) for col in range(row + 1, n)):
            raise FrameError("mass_matrix must be exactly symmetric")
        if any(len(values) != n for values in (q, qdot, qddot, base)) or len(force) != 3 * self.model.slices:
            raise FrameError("kernel state/force dimensions are inconsistent with model")
        _bounded_int(self.sequence, "sequence", 1, 0xFFFFFFFF)
        _bounded_int(self.global_step, "global_step", 1, 0x7FFFFFFF)
        _bounded_int(self.case_local_bridge_step, "case_local_bridge_step", 1, 0x7FFFFFFF)
        _bounded_int(self.integer_tick, "integer_tick", 0, 0xFFFFFFFFFFFFFFFF)
        _bounded_int(self.request_id, "request_id", 1, 0xFFFFFFFFFFFFFFFF)
        _bounded_int(self.transaction_id, "transaction_id", 1, 0xFFFFFFFFFFFFFFFF)
        if not math.isfinite(float(self.time_s)) or not math.isfinite(float(self.dt_s)):
            raise FrameError("kernel time is NaN/Inf")
        if self.dt_s <= 0.0:
            raise FrameError("kernel dt_s must be positive")
        canonical_tick_delta(self.dt_s)
        expected_tick = canonical_integer_tick(self.time_s)
        if (self.time_s < self.dt_s or self.time_s > 1.0e9 or
                expected_tick < 0 or expected_tick > 0xFFFFFFFFFFFFFFFF or
                self.integer_tick != expected_tick):
            raise FrameError("kernel time_s and integer_tick are inconsistent")
        alpha = float(self.model.damping_alpha)
        beta = float(self.model.damping_beta)
        has_damping = alpha != 0.0 or beta != 0.0
        if self.damping_mode not in ("none", "rayleigh_coefficients"):
            raise FrameError("damping mode is unknown")
        if has_damping:
            if self.damping_mode != "rayleigh_coefficients" or self.damping_reference_state != "dynamic_initial":
                raise FrameError("non-zero damping requires the dynamic_initial Rayleigh contract")
            if self.damping_psd_policy_id != DAMPING_PSD_POLICY_ID:
                raise FrameError("unsupported damping PSD policy")
            q_ref = _finite_vector(self.damping_q_ref, "damping.q_ref")
            if len(q_ref) != n:
                raise FrameError("damping.q_ref dimension is inconsistent with model")
            expected_damping = damping_identity_sha256(alpha, beta,
                                                       psd_policy_id=self.damping_psd_policy_id)
            if self.damping_identity_sha256.lower() != expected_damping:
                raise FrameError("damping identity does not match coefficients")
            expected_reference = damping_reference_state_sha256(
                q_ref, self.damping_model_identity_sha256)
            if self.damping_reference_state_identity_sha256.lower() != expected_reference:
                raise FrameError("damping reference identity does not match q_ref")
            try:
                damping_identity = bytes.fromhex(self.damping_identity_sha256)
                reference_identity = bytes.fromhex(self.damping_reference_state_identity_sha256)
                model_identity = bytes.fromhex(self.damping_model_identity_sha256)
            except ValueError as exc:
                raise FrameError("damping identities must be SHA-256 hex") from exc
            damping_extension = (
                struct.pack("<6I", DAMPING_EXTENSION_MARKER, DAMPING_EXTENSION_VERSION,
                            DAMPING_MODE_RAYLEIGH, DAMPING_REFERENCE_DYNAMIC_INITIAL,
                            n, self.damping_psd_policy_id) + damping_identity +
                reference_identity + model_identity +
                struct.pack("<" + "d" * n, *q_ref))
        else:
            if self.damping_mode != "none" or alpha != 0.0 or beta != 0.0:
                raise FrameError("zero damping must use mode none")
            if self.damping_q_ref:
                raise FrameError("none damping must not carry q_ref")
            damping_extension = b""
        prefix = _PREFIX.pack(SCHEMA_VERSION, PROTOCOL_VERSION, self.sequence, self.global_step,
                              self.case_local_bridge_step, self.integer_tick, self.time_s, self.dt_s,
                              n, self.model.elements, self.model.slices, self.model.gauss_order,
                              self.model.max_newton, self.request_id, self.transaction_id)
        model_bytes = self.model.bytes() + damping_extension
        if mass:
            sizes = struct.pack("<iii", len(base), len(force), n)
        else:
            # Preserve the original frame layout for legacy callers.
            sizes = struct.pack("<ii", len(base), len(force))
        ids = (_fixed(self.run_id, ID_RUN, "run_id") + _fixed(self.case_id, ID_CASE, "case_id") +
               _fixed(self.producer, ID_ENDPOINT, "producer") + _fixed(self.consumer, ID_ENDPOINT, "consumer"))
        arrays = struct.pack("<" + "d" * (4 * n + len(mass) + len(force)),
                             *(q + qdot + qddot + base + mass + force))
        digest = hashlib.sha256(model_bytes + arrays).digest()
        return prefix + model_bytes + sizes + ids + digest + arrays


def encode_kernel_request(value: KernelStepRequest) -> bytes:
    payload = value.payload()
    return HEADER.pack(MAGIC, len(payload), MESSAGE_KERNEL_STEP_REQUEST) + payload


@dataclass(frozen=True)
class KernelStepResponse:
    sequence: int
    global_step: int
    case_local_bridge_step: int
    integer_tick: int
    time_s: float
    return_code: int
    iterations: int
    residual: float
    payload_hash: bytes
    transaction_id: int
    request_id: int
    ack: int
    run_id: str
    case_id: str
    producer: str
    consumer: str
    q: tuple[float, ...]
    qdot: tuple[float, ...]
    qddot: tuple[float, ...]
    internal_force: tuple[float, ...]
    external_force: tuple[float, ...]
    generalized_force: tuple[float, ...]
    predictor: tuple[float, ...]
    corrector: tuple[float, ...]
    checkpoint_step: int
    checkpoint_time_s: float
    checkpoint_tick: int
    finite_value_audit: bool


def _clean(value: bytes) -> str:
    if b"\0" not in value:
        raise FrameError("kernel identity is not NUL-terminated")
    raw, trailing = value.split(b"\0", 1)
    if not raw or any(trailing):
        raise FrameError("kernel identity has invalid fixed-width encoding")
    try:
        result = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrameError("kernel identity is not UTF-8") from exc
    if any(ord(char) < 0x20 for char in result):
        raise FrameError("kernel identity contains a control character")
    return result


def decode_kernel_response(frame: bytes) -> KernelStepResponse:
    if len(frame) < HEADER.size:
        raise FrameError("kernel response is truncated")
    magic, length, message_type = HEADER.unpack_from(frame)
    if magic != MAGIC or message_type != MESSAGE_KERNEL_STEP_RESPONSE or length != len(frame) - HEADER.size:
        raise FrameError("kernel response header mismatch")
    raw = frame[HEADER.size:]
    fixed = _RESPONSE_PREFIX.size + ID_RUN + ID_CASE + ID_ENDPOINT + ID_ENDPOINT + 32
    if len(raw) < fixed:
        raise FrameError("kernel response payload is truncated")
    (schema, protocol, sequence, step, bridge, tick, time_s, n, code,
     iterations, residual, tx, request_id, ack) = _RESPONSE_PREFIX.unpack_from(raw)
    # Reject the dimension before calculating vector_count or unpacking any
    # response arrays.  A malformed frame must not turn the response decoder
    # into an unbounded allocation path.
    if (schema != SCHEMA_VERSION or protocol != PROTOCOL_VERSION or
            n <= 0 or n > MAX_NDOF):
        raise FrameError("kernel response schema or dimension is invalid")
    offset = _RESPONSE_PREFIX.size
    run = _clean(raw[offset:offset + ID_RUN]); offset += ID_RUN
    case = _clean(raw[offset:offset + ID_CASE]); offset += ID_CASE
    producer = _clean(raw[offset:offset + ID_ENDPOINT]); offset += ID_ENDPOINT
    consumer = _clean(raw[offset:offset + ID_ENDPOINT]); offset += ID_ENDPOINT
    digest = raw[offset:offset + 32]; offset += 32
    vector_count = 8 * n
    vector_bytes = 8 * vector_count
    trailer = struct.Struct("<QdQI")
    if len(raw) != offset + vector_bytes + trailer.size:
        raise FrameError("kernel response vector length mismatch")
    values = struct.unpack_from("<" + "d" * vector_count, raw, offset); offset += vector_bytes
    checkpoint_step, checkpoint_time, checkpoint_tick, finite_audit = trailer.unpack_from(raw, offset)
    if (any(not math.isfinite(value) for value in values) or not math.isfinite(time_s) or
            not math.isfinite(residual) or finite_audit != 1):
        raise FrameError("kernel response contains NaN/Inf")
    fields = [tuple(values[index * n:(index + 1) * n]) for index in range(8)]
    return KernelStepResponse(sequence, step, bridge, tick, time_s, code, iterations, residual,
                              bytes(digest), tx, request_id, ack, run, case, producer, consumer,
                              *fields, checkpoint_step, checkpoint_time, checkpoint_tick,
                              bool(finite_audit))


def validate_kernel_response(request: KernelStepRequest, response: KernelStepResponse) -> None:
    if (response.sequence != request.sequence or response.global_step != request.global_step or
        response.case_local_bridge_step != request.case_local_bridge_step or
        response.integer_tick != request.integer_tick or
        not math.isclose(response.time_s, request.time_s, rel_tol=0.0, abs_tol=1e-12)):
        raise FrameError("kernel response identity mismatch")
    if response.transaction_id != request.transaction_id or response.request_id != request.request_id or response.ack != 1:
        raise FrameError("kernel response acknowledgement mismatch")
    if response.run_id != request.run_id or response.case_id != request.case_id:
        raise FrameError("kernel response run/case mismatch")
    if response.producer != request.consumer or response.consumer != request.producer:
        raise FrameError("kernel response producer/consumer mismatch")
    if response.return_code != 0 or not response.finite_value_audit:
        raise FrameError("kernel worker returned failure or non-finite state")
    if len(response.q) != request.model.ndof or len(response.qdot) != request.model.ndof or len(response.qddot) != request.model.ndof:
        raise FrameError("kernel response state dimension mismatch")
    if any(len(field) != request.model.ndof for field in (
        response.internal_force, response.external_force, response.generalized_force,
        response.predictor, response.corrector)):
        raise FrameError("kernel response field dimension mismatch")
    if response.checkpoint_step != request.global_step or response.checkpoint_tick != request.integer_tick:
        raise FrameError("kernel checkpoint identity mismatch")
    if not math.isfinite(response.checkpoint_time_s) or not math.isclose(
        response.checkpoint_time_s, request.time_s, rel_tol=0.0, abs_tol=1e-12):
        raise FrameError("kernel checkpoint time mismatch")
    arrays = response.q + response.qdot + response.qddot + response.internal_force + response.external_force + response.generalized_force + response.predictor + response.corrector
    actual = hashlib.sha256(struct.pack("<" + "d" * len(arrays), *arrays)).digest()
    if response.payload_hash != actual:
        raise FrameError("kernel response payload hash mismatch")
