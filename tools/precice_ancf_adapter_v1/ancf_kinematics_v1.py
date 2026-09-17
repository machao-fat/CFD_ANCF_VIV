"""Shared arbitrary-s ANCF kinematics for the generic participant.

The implementation delegates shape-matrix construction to the repository's
canonical ``multi_slice_mapping`` helper.  No historical q-index projection
is used here.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Sequence, Tuple


def _ensure_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src = str(repo_root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


_ensure_src_on_path()

from coupling.multi_slice_mapping.mapping import (  # noqa: E402
    MappingError,
    ancf_hermite_H,
    interpolate_ancf_state,
)


NODE_DOF_STRIDE = 6
NODE_DOF_ORDER = ("r_x", "r_y", "r_z", "r_sx", "r_sy", "r_sz")


class KinematicsError(ValueError):
    """Invalid ANCF state, mesh or material coordinate."""


def _finite(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise KinematicsError(f"{name} must be numeric") from exc
    import math

    if not math.isfinite(result):
        raise KinematicsError(f"{name} must be finite")
    return result


def _positive(value: object, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise KinematicsError(f"{name} must be positive")
    return result


def _mesh_nodes(length_m: object, elements: object) -> Tuple[float, ...]:
    length = _positive(length_m, "length_m")
    if isinstance(elements, bool) or not isinstance(elements, int) or elements < 1:
        raise KinematicsError("elements must be an integer >= 1")
    return tuple(length * i / elements for i in range(elements + 1))


def shape_functions(local_x_m: object, element_length_m: object) -> Tuple[float, float, float, float]:
    """Return the production Hermite functions using xi=x/L_e in [0,1]."""

    x = _finite(local_x_m, "local_x_m")
    length = _positive(element_length_m, "element_length_m")
    xi = x / length
    if xi < -1.0e-12 or xi > 1.0 + 1.0e-12:
        raise KinematicsError("local_x_m lies outside the element")
    xi = min(1.0, max(0.0, xi))
    return (
        1.0 - 3.0 * xi * xi + 2.0 * xi * xi * xi,
        length * (xi - 2.0 * xi * xi + xi * xi * xi),
        3.0 * xi * xi - 2.0 * xi * xi * xi,
        length * (-xi * xi + xi * xi * xi),
    )


def shape_function_derivatives(local_x_m: object, element_length_m: object) -> Tuple[float, float, float, float]:
    """Return d(N1,N2,N3,N4)/dx for the canonical ANCF Hermite element."""

    x = _finite(local_x_m, "local_x_m")
    length = _positive(element_length_m, "element_length_m")
    xi = x / length
    if xi < -1.0e-12 or xi > 1.0 + 1.0e-12:
        raise KinematicsError("local_x_m lies outside the element")
    xi = min(1.0, max(0.0, xi))
    return (
        (-6.0 * xi + 6.0 * xi * xi) / length,
        1.0 - 4.0 * xi + 3.0 * xi * xi,
        (6.0 * xi - 6.0 * xi * xi) / length,
        -2.0 * xi + 3.0 * xi * xi,
    )

def shape_matrix(s_m: object, length_m: object, elements: int) -> Tuple[Tuple[float, ...], ...]:
    """Return the 3 x ndof canonical ANCF position matrix at s."""

    nodes = _mesh_nodes(length_m, elements)
    try:
        return ancf_hermite_H(s_m, nodes, ndof=NODE_DOF_STRIDE * (elements + 1))
    except MappingError as exc:
        raise KinematicsError(str(exc)) from exc


def _mat_vec(matrix: Sequence[Sequence[float]], vector: Sequence[float], name: str) -> Tuple[float, float, float]:
    if len(vector) != len(matrix[0]):
        raise KinematicsError(f"{name} dimension does not match ANCF model")
    values = []
    for row in matrix:
        values.append(sum(float(a) * float(b) for a, b in zip(row, vector)))
    return tuple(values)  # type: ignore[return-value]


def position_at_s(q: Sequence[float], s_m: object, length_m: object, elements: int) -> Tuple[float, float, float]:
    return _mat_vec(shape_matrix(s_m, length_m, elements), q, "q")


def velocity_at_s(qdot: Sequence[float], s_m: object, length_m: object, elements: int) -> Tuple[float, float, float]:
    return _mat_vec(shape_matrix(s_m, length_m, elements), qdot, "qdot")


def acceleration_at_s(qddot: Sequence[float], s_m: object, length_m: object, elements: int) -> Tuple[float, float, float]:
    return _mat_vec(shape_matrix(s_m, length_m, elements), qddot, "qddot")


def gradient_at_s(q: Sequence[float], s_m: object, length_m: object,
                  elements: int) -> Tuple[float, float, float]:
    """Interpolate the material gradient r_s at an arbitrary reference s."""

    length = _positive(length_m, "length_m")
    if isinstance(elements, bool) or not isinstance(elements, int) or elements < 1:
        raise KinematicsError("elements must be an integer >= 1")
    s = _finite(s_m, "s_m")
    if s < 0.0 or s > length:
        raise KinematicsError("s_m lies outside the model")
    if len(q) != NODE_DOF_STRIDE * (elements + 1):
        raise KinematicsError("q dimension does not match ANCF model")
    element_length = length / elements
    element = elements - 1 if s == length else min(elements - 1, int(s / element_length))
    local_x = s - element * element_length
    d1, d2, d3, d4 = shape_function_derivatives(local_x, element_length)
    values = tuple(float(value) for value in q)
    result = []
    for component in range(3):
        result.append(
            d1 * values[6 * element + component]
            + d2 * values[6 * element + 3 + component]
            + d3 * values[6 * (element + 1) + component]
            + d4 * values[6 * (element + 1) + 3 + component]
        )
    return tuple(result)  # type: ignore[return-value]


def interpolate_state(
    q: Sequence[float],
    qdot: Sequence[float],
    qddot: Sequence[float],
    s_m: object,
    length_m: object,
    elements: int,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]:
    matrix = shape_matrix(s_m, length_m, elements)
    return (
        _mat_vec(matrix, q, "q"),
        _mat_vec(matrix, qdot, "qdot"),
        _mat_vec(matrix, qddot, "qddot"),
    )
