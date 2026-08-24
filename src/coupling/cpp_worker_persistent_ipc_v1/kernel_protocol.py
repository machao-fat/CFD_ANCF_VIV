from __future__ import annotations

import hashlib
import math
from numbers import Real
import struct
from dataclasses import dataclass
from typing import BinaryIO, Sequence

from .protocol import FrameError, HEADER, MAGIC, SCHEMA_VERSION, PROTOCOL_VERSION


MESSAGE_KERNEL_STEP_REQUEST = 5
MESSAGE_KERNEL_STEP_RESPONSE = 6
ID_RUN = 64
ID_CASE = 64
ID_ENDPOINT = 32
MAX_NDOF = 2048

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
_RESPONSE_PREFIX = struct.Struct("<IIIiiQdiiidQQI")


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
    max_newton: int = 40
    slice_positions_m: tuple[float, ...] = ()
    # Kept explicit in the model object even though the v1 wire layout
    # intentionally requires both owned components to be enabled.
    include_gravity: bool = True
    include_buoyancy: bool = True

    @property
    def ndof(self) -> int:
        if isinstance(self.elements, bool) or not isinstance(self.elements, int):
            raise FrameError("kernel elements is not an integer")
        return 6 * (self.elements + 1)

    def validate(self, dt_s: float) -> None:
        for name, value in (("elements", self.elements), ("slices", self.slices),
                            ("gauss_order", self.gauss_order), ("max_newton", self.max_newton)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise FrameError(f"kernel model {name} is not an integer")
        if (self.elements < 1 or self.elements > 10000 or self.slices < 1 or
                self.slices > 1000 or self.ndof > MAX_NDOF or self.gauss_order not in (3, 5)):
            raise FrameError("kernel model dimensions or quadrature order are invalid")
        if self.max_newton <= 0 or self.newton_tolerance <= 0.0:
            raise FrameError("kernel Newton contract is invalid")
        if self.damping_alpha != 0.0 or self.damping_beta != 0.0:
            raise FrameError("non-zero damping is not implemented in the worker contract")
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
        if isinstance(self.slice_positions_m, (str, bytes)):
            raise FrameError("kernel slice positions are not numeric")
        if self.slice_positions_m and (len(self.slice_positions_m) != self.slices or
                                       any(isinstance(x, bool) or not isinstance(x, Real) or
                                           not math.isfinite(float(x)) or x < 0.0 or x > self.length_m
                                           for x in self.slice_positions_m) or
                                       any(self.slice_positions_m[i] <= self.slice_positions_m[i - 1]
                                           for i in range(1, len(self.slice_positions_m)))):
            raise FrameError("kernel slice positions are invalid")

    def bytes(self) -> bytes:
        self.validate(1.0)
        positions = self.slice_positions_m or tuple(self.length_m * k / max(1, self.slices - 1) for k in range(self.slices))
        return _MODEL.pack(self.length_m, self.diameter_m, self.inner_diameter_m,
                           self.top_tension_N, self.youngs_modulus_Pa, self.material_density,
                           self.fluid_density, self.gravity, self.beta, self.gamma,
                           self.newton_tolerance, self.damping_alpha, self.damping_beta,
                           self.gauss_order, self.max_newton) + struct.pack("<" + "d" * self.slices, *positions)


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

    def payload(self) -> bytes:
        self.model.validate(self.dt_s)
        n = self.model.ndof
        q = _finite_vector(self.q, "q"); qdot = _finite_vector(self.qdot, "qdot")
        qddot = _finite_vector(self.qddot, "qddot"); base = _finite_vector(self.base_load, "base_load")
        force = _finite_vector(self.slice_force, "slice_force")
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
        expected_tick = int(round(self.time_s * 1.0e9))
        if (self.time_s < self.dt_s or self.time_s > 1.0e9 or
                expected_tick < 0 or expected_tick > 0xFFFFFFFFFFFFFFFF or
                self.integer_tick != expected_tick):
            raise FrameError("kernel time_s and integer_tick are inconsistent")
        prefix = _PREFIX.pack(SCHEMA_VERSION, PROTOCOL_VERSION, self.sequence, self.global_step,
                              self.case_local_bridge_step, self.integer_tick, self.time_s, self.dt_s,
                              n, self.model.elements, self.model.slices, self.model.gauss_order,
                              self.model.max_newton, self.request_id, self.transaction_id)
        model_bytes = self.model.bytes()
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
    if schema != SCHEMA_VERSION or protocol != PROTOCOL_VERSION or n <= 0:
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
    if any(not math.isfinite(value) for value in values) or not math.isfinite(time_s) or not math.isfinite(residual):
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
