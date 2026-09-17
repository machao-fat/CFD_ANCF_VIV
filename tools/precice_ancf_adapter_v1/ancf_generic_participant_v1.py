"""Generic N-slice ANCF participant with injectable offline backends.

No live preCICE object is created by this module unless a caller injects a
backend that does so.  The default development/test path is therefore safe
for pure contract tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence

from .ancf_case_config_v1 import CaseConfig, CaseConfigError, FORCE_REPRESENTATION
from .ancf_kinematics_v1 import interpolate_state


try:
    from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
    from coupling.cpp_worker_persistent_ipc_v1.protocol import canonical_integer_tick
    from coupling.multi_slice_mapping.mapping import convert_openfoam_force
except ModuleNotFoundError:  # pragma: no cover - supports direct script imports
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest  # type: ignore
    from coupling.cpp_worker_persistent_ipc_v1.protocol import canonical_integer_tick  # type: ignore
    from coupling.multi_slice_mapping.mapping import convert_openfoam_force  # type: ignore


class ParticipantError(RuntimeError):
    """Generic participant contract error."""


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ParticipantError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ParticipantError(f"{name} must be finite")
    return result


def _force_total(value: Any, name: str) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        value = value.get("force_N", value.get("force"))
    if value is None or isinstance(value, (str, bytes)):
        raise ParticipantError(f"{name} has no force payload")
    try:
        rows = list(value)
    except TypeError as exc:
        raise ParticipantError(f"{name} is not a sequence") from exc
    if len(rows) == 3 and all(not isinstance(item, (list, tuple)) for item in rows):
        return tuple(_finite(item, f"{name}[{i}]") for i, item in enumerate(rows))  # type: ignore[return-value]
    result = [0.0, 0.0, 0.0]
    if not rows:
        raise ParticipantError(f"{name} has no force rows")
    for row_index, row in enumerate(rows):
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence) or len(row) not in (2, 3):
            raise ParticipantError(f"{name}[{row_index}] must be a 2-D or 3-D vector")
        for axis in range(len(row)):
            result[axis] += _finite(row[axis], f"{name}[{row_index}][{axis}]")
    return tuple(result)


def _response_field(response: Any, name: str) -> tuple[float, ...]:
    value = response.get(name) if isinstance(response, Mapping) else getattr(response, name, None)
    if value is None:
        raise ParticipantError(f"worker response missing {name}")
    try:
        result = tuple(_finite(item, f"response.{name}") for item in value)
    except TypeError as exc:
        raise ParticipantError(f"response.{name} is not a sequence") from exc
    return result


@dataclass(frozen=True)
class SliceStep:
    slice_id: int
    displacement_m: tuple[float, float]
    force_openfoam_N: tuple[float, float, float]
    force_integrated_N: tuple[float, float, float]
    position_m: tuple[float, float, float]
    velocity_mps: tuple[float, float, float]
    acceleration_mps2: tuple[float, float, float]


@dataclass(frozen=True)
class ParticipantStep:
    request: Any
    response: Any
    slices: tuple[SliceStep, ...]
    time_s: float
    global_step: int


class GenericANCFParticipant:
    """Drive an arbitrary configured slice set through the existing worker API."""

    def __init__(self, config: CaseConfig, backends: Sequence[Any], worker: Any,
                 *, vertex_count: int | None = None) -> None:
        self.config = config
        if len(backends) != len(config.slices()):
            raise ParticipantError("backend count must equal configured slice count")
        self.backends = tuple(backends)
        self.worker = worker
        self.vertex_count = vertex_count
        state = config.initial_state()
        boundary_override = None
        if "boundary_fixed_dof" in state and "boundary_prescribed_values" in state:
            boundary_override = (state["boundary_fixed_dof"], state["boundary_prescribed_values"])
        self.model = config.kernel_model(boundary_override)
        self.q = tuple(state["q"]); self.qdot = tuple(state["qdot"]); self.qddot = tuple(state["qddot"])
        self.base_load = tuple(state["base_load"])
        self.time_s = float(state["time_s"])
        self.global_step = int(state["global_step"])
        self._initialized = False
        self.history: list[ParticipantStep] = []

    def initialize(self) -> None:
        if self._initialized:
            raise ParticipantError("participant already initialized")
        for backend in self.backends:
            initialize = getattr(backend, "initialize", None)
            if callable(initialize):
                initialize()
        self._initialized = True

    def _write_motion(self, backend: Any, displacement: tuple[float, float]) -> None:
        count = self.vertex_count
        if count is None:
            count = int(getattr(backend, "vertex_count", 1))
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ParticipantError("vertex_count must be a positive integer")
        payload = {"displacement_m": [list(displacement) for _ in range(count)]}
        writer = getattr(backend, "write_displacement", None)
        if not callable(writer):
            raise ParticipantError("backend lacks write_displacement")
        writer(payload)

    def _read_force(self, backend: Any, item: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        reader = getattr(backend, "read_force", None)
        if not callable(reader):
            raise ParticipantError("backend lacks read_force")
        raw = reader()
        openfoam = _force_total(raw, "preCICE Force")
        converted = convert_openfoam_force(openfoam, item.unit_span_m, item.slice_length_m)
        return openfoam, converted.force_N

    def _send_worker(self, request: Any) -> Any:
        if callable(self.worker):
            return self.worker(request)
        step = getattr(self.worker, "step", None)
        if callable(step):
            return step(request)
        raise ParticipantError("worker must be callable or expose step(request)")

    def step(self) -> ParticipantStep:
        if not self._initialized:
            raise ParticipantError("participant must be initialized")
        positions = self.config.reference_positions()
        slice_defs = self.config.slices()
        motion_data = []
        for index, item in enumerate(slice_defs):
            position, velocity, acceleration = interpolate_state(
                self.q, self.qdot, self.qddot, item.s_ref_m, self.config.length_m, self.config.elements)
            reference = positions[index]
            displacement = (position[0] - reference[0], position[1] - reference[1])
            if not all(math.isfinite(value) for value in displacement):
                raise ParticipantError("non-finite relative displacement")
            self._write_motion(self.backends[index], displacement)
            motion_data.append((item, position, velocity, acceleration, displacement))
        for backend in self.backends:
            advance = getattr(backend, "advance", None)
            if not callable(advance):
                raise ParticipantError("backend lacks advance")
            advance(float(self.config.raw["numerics"]["dt_s"]))
        forces = []
        slice_steps = []
        for index, (item, position, velocity, acceleration, displacement) in enumerate(motion_data):
            openfoam, force = self._read_force(self.backends[index], item)
            forces.extend(force)
            slice_steps.append(SliceStep(item.slice_id, displacement, openfoam, force,
                                         position, velocity, acceleration))
        dt = float(self.config.raw["numerics"]["dt_s"])
        next_step = self.global_step + 1
        next_time = self.time_s + dt
        request_obj = KernelStepRequest(
            sequence=next_step, global_step=next_step, case_local_bridge_step=next_step,
            integer_tick=canonical_integer_tick(next_time), time_s=next_time, dt_s=dt,
            request_id=next_step, transaction_id=next_step, run_id=self.config.run_id,
            case_id=self.config.case_id, model=self.model, q=self.q, qdot=self.qdot,
            qddot=self.qddot, base_load=self.base_load,
            slice_force=tuple(forces),
        )
        response = self._send_worker(request_obj)
        q = _response_field(response, "q"); qdot = _response_field(response, "qdot"); qddot = _response_field(response, "qddot")
        if any(len(value) != self.model.ndof for value in (q, qdot, qddot)):
            raise ParticipantError("worker response state dimension mismatch")
        self.q, self.qdot, self.qddot = q, qdot, qddot
        self.time_s, self.global_step = next_time, next_step
        result = ParticipantStep(request_obj, response, tuple(slice_steps), self.time_s, self.global_step)
        self.history.append(result)
        return result

    def state_artifact(self) -> dict[str, Any]:
        return self.config.make_state_artifact(self.q, self.qdot, self.qddot, self.time_s, self.global_step)

    def finalize(self) -> None:
        for backend in self.backends:
            finalize = getattr(backend, "finalize", None)
            if callable(finalize) and self._initialized:
                finalize()
        self._initialized = False
