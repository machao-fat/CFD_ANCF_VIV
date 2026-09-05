from __future__ import annotations

import math
from typing import Iterable, Sequence


class ContractError(ValueError):
    pass


def bounded_midpoint_voronoi(positions_m: Sequence[float], interval_m: Sequence[float]) -> tuple[tuple[float, float, float], ...]:
    """Return ``(left, centre, right)`` partitions without a slice-count default."""
    if len(interval_m) != 2:
        raise ContractError("represented interval must have two endpoints")
    left, right = (float(interval_m[0]), float(interval_m[1]))
    positions = tuple(float(value) for value in positions_m)
    if not (math.isfinite(left) and math.isfinite(right) and left < right and positions):
        raise ContractError("partition inputs are invalid")
    if any(not math.isfinite(value) for value in positions) or any(a >= b for a, b in zip(positions, positions[1:])):
        raise ContractError("slice reference positions must be finite and strictly increasing")
    if positions[0] < left or positions[-1] > right:
        raise ContractError("slice reference positions lie outside represented interval")
    edges = [left] + [(a + b) / 2.0 for a, b in zip(positions, positions[1:])] + [right]
    result = tuple((edges[index], centre, edges[index + 1]) for index, centre in enumerate(positions))
    if any(not row[0] <= row[1] <= row[2] or row[2] <= row[0] for row in result):
        raise ContractError("degenerate tributary partition")
    if not math.isclose(sum(row[2] - row[0] for row in result), right - left, rel_tol=0.0, abs_tol=1e-12):
        raise ContractError("tributary lengths do not cover represented length")
    return result


def finite_rows(rows: Iterable[Sequence[float]], width: int) -> bool:
    try:
        return all(len(row) == width and all(math.isfinite(float(value)) for value in row) for row in rows)
    except TypeError:
        return False
