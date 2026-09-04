from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


DEFAULT_LENGTH_M = 50.0
DEFAULT_ELEMENTS = 16
DEFAULT_SLICE_POSITIONS_M = (8.333333333333334, 25.0, 41.666666666666664)


class MappingError(ValueError):
    pass


def _finite_vector(values: Sequence[float], name: str) -> tuple[float, ...]:
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise MappingError(f"{name} is not numeric") from exc
    if not result or any(not math.isfinite(value) for value in result):
        raise MappingError(f"{name} is empty or non-finite")
    return result


def _shape(x: float, element_length: float) -> tuple[float, float, float, float]:
    """The same scalar-power Hermite shape contract as ancf_kernel.cpp."""
    xi = x / element_length
    xi2 = math.pow(xi, 2.0)
    xi3 = math.pow(xi, 3.0)
    return (
        1.0 - 3.0 * xi2 + 2.0 * xi3,
        element_length * (xi - 2.0 * xi2 + xi3),
        3.0 * xi2 - 2.0 * xi3,
        element_length * (-xi2 + xi3),
    )


def canonical_h_row(
    position_m: float,
    *,
    length_m: float = DEFAULT_LENGTH_M,
    elements: int = DEFAULT_ELEMENTS,
) -> tuple[float, ...]:
    """Return one 3D ANCF interpolation row in the worker's DOF order."""
    if not math.isfinite(float(position_m)) or not 0.0 <= position_m <= length_m:
        raise MappingError("slice position is outside the case")
    if elements < 1 or not math.isfinite(float(length_m)) or length_m <= 0.0:
        raise MappingError("invalid case geometry")
    element_length = length_m / elements
    element = elements - 1 if position_m == length_m else min(elements - 1, int(math.floor(position_m / element_length)))
    x = position_m - element * element_length
    shape = _shape(x, element_length)
    row = [0.0] * (6 * (elements + 1))
    # C++ block_matrix order is node xyz, node slope xyz, next node xyz, next slope xyz.
    offsets = (6 * element, 6 * element + 3, 6 * (element + 1), 6 * (element + 1) + 3)
    for coefficient, offset in zip(shape, offsets):
        for component in range(3):
            row[offset + component] = coefficient
    return tuple(row)


def _dot(row: Sequence[float], values: Sequence[float]) -> float:
    if len(row) != len(values):
        raise MappingError("H row and state dimension mismatch")
    return sum(float(a) * float(b) for a, b in zip(row, values))


def _project_component(values: Sequence[float], *, position_m: float, component: int,
                       length_m: float, elements: int) -> float:
    if component not in (0, 1, 2):
        raise MappingError("component must be x, y, or z")
    if not math.isfinite(float(position_m)) or not 0.0 <= position_m <= length_m:
        raise MappingError("slice position is outside the case")
    element_length = length_m / elements
    element = elements - 1 if position_m == length_m else min(elements - 1, int(math.floor(position_m / element_length)))
    shape = _shape(position_m - element * element_length, element_length)
    indices = (6 * element + component, 6 * element + 3 + component,
               6 * (element + 1) + component, 6 * (element + 1) + 3 + component)
    return sum(coefficient * float(values[index]) for coefficient, index in zip(shape, indices))


def project_interface(
    q: Sequence[float],
    qdot: Sequence[float],
    *,
    slice_positions_m: Sequence[float] = DEFAULT_SLICE_POSITIONS_M,
    length_m: float = DEFAULT_LENGTH_M,
    elements: int = DEFAULT_ELEMENTS,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Project positions and velocities with exactly the worker's H rows.

    preCICE is two-dimensional, so x/y are exported while all three components
    remain in the audit records for identity and power checks.
    """
    qv = _finite_vector(q, "q")
    qdv = _finite_vector(qdot, "qdot")
    if len(qv) != 6 * (elements + 1) or len(qdv) != len(qv):
        raise MappingError("state dimension does not match elements")
    positions: list[tuple[float, float, float]] = []
    velocities: list[tuple[float, float, float]] = []
    for position in slice_positions_m:
        positions.append(tuple(_project_component(qv, position_m=position, component=component,
                                                   length_m=length_m, elements=elements)
                              for component in range(3)))
        velocities.append(tuple(_project_component(qdv, position_m=position, component=component,
                                                    length_m=length_m, elements=elements)
                               for component in range(3)))
    return (
        [(value[0], value[1]) for value in positions],
        [(value[0], value[1]) for value in velocities],
        positions,
        velocities,
    )


def _mapped_force(slice_force: Sequence[Sequence[float]], rows: Sequence[Sequence[float]], ndof: int) -> tuple[float, ...]:
    if len(slice_force) != len(rows) or any(len(force) != 3 for force in slice_force):
        raise MappingError("slice force dimensions are invalid")
    result = [0.0] * ndof
    # Each H row is reused for x/y/z, but only the matching component DOFs
    # receive that component's force. This is H^T F in the worker's block order.
    for force, row in zip(slice_force, rows):
        for component in range(3):
            if not math.isfinite(float(force[component])):
                raise MappingError("slice force contains NaN/Inf")
            for index, coefficient in enumerate(row):
                block = index % 6
                if block in (component, component + 3):
                    result[index] += float(coefficient) * float(force[component])
    return tuple(result)


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


@dataclass(frozen=True)
class MappingAudit:
    fluid_power: float
    mapped_power: float
    virtual_work_error: float
    force_balance_error: float
    moment_balance_error: float
    fluid_resultant: tuple[float, float, float]
    mapped_resultant: tuple[float, float, float]


def diagnose_mapping(
    q: Sequence[float],
    qdot: Sequence[float],
    slice_force: Sequence[Sequence[float]],
    *,
    slice_positions_m: Sequence[float] = DEFAULT_SLICE_POSITIONS_M,
    length_m: float = DEFAULT_LENGTH_M,
    elements: int = DEFAULT_ELEMENTS,
) -> MappingAudit:
    """Audit work, resultant and rigid-rotation moment using one canonical H."""
    if len(slice_force) != len(slice_positions_m):
        raise MappingError("slice force/position count mismatch")
    qv = _finite_vector(q, "q")
    qdv = _finite_vector(qdot, "qdot")
    _, _, positions, projected_velocity = project_interface(
        qv, qdv, slice_positions_m=slice_positions_m, length_m=length_m, elements=elements
    )
    rows = [canonical_h_row(position, length_m=length_m, elements=elements) for position in slice_positions_m]
    ndof = len(qv)
    mapped = _mapped_force(slice_force, rows, ndof)
    fluid_power = sum(float(force[c]) * projected_velocity[i][c] for i, force in enumerate(slice_force) for c in range(3))
    mapped_power = sum(mapped[i] * qdv[i] for i in range(ndof))
    work_scale = max(abs(fluid_power), abs(mapped_power), 1.0e-30)

    fluid_resultant = tuple(sum(float(force[c]) for force in slice_force) for c in range(3))
    mapped_resultant = tuple(
        sum(mapped[6 * node + component] for node in range(elements + 1))
        for component in range(3)
    )
    force_scale = max(max(abs(value) for value in fluid_resultant), 1.0e-30)

    # Rigid rotation about the global z axis: positions and ANCF slopes rotate together.
    rotation_virtual_q = [0.0] * ndof
    for node in range(elements + 1):
        base = 6 * node
        point = qv[base:base + 3]
        slope = qv[base + 3:base + 6]
        delta_point = _cross((0.0, 0.0, 1.0), point)
        delta_slope = _cross((0.0, 0.0, 1.0), slope)
        rotation_virtual_q[base:base + 3] = delta_point
        rotation_virtual_q[base + 3:base + 6] = delta_slope
    mapped_moment = sum(mapped[i] * rotation_virtual_q[i] for i in range(ndof))
    fluid_moment = sum(float(force[0]) * (-position[1]) + float(force[1]) * position[0] for force, position in zip(slice_force, positions))
    moment_scale = max(abs(fluid_moment), abs(mapped_moment), 1.0e-30)
    return MappingAudit(
        fluid_power=fluid_power,
        mapped_power=mapped_power,
        virtual_work_error=abs(fluid_power - mapped_power) / work_scale,
        force_balance_error=max(abs(a - b) for a, b in zip(fluid_resultant, mapped_resultant)) / force_scale,
        moment_balance_error=abs(fluid_moment - mapped_moment) / moment_scale,
        fluid_resultant=fluid_resultant,
        mapped_resultant=mapped_resultant,
    )
