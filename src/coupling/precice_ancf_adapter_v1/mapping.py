from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .protocol import canonical_tick


class MappingError(ValueError):
    pass


@dataclass(frozen=True)
class BridgeClock:
    """One canonical clock; local bridge numbering is intentionally independent."""

    global_origin: int
    local_origin: int
    time_origin_s: float
    dt_s: float = 0.005

    def __post_init__(self) -> None:
        if self.global_origin < 0 or self.local_origin < 0 or self.dt_s != 0.005:
            raise MappingError("Stage 285 requires non-negative origins and dt_s=0.005")
        if not math.isfinite(self.time_origin_s) or self.time_origin_s < 0:
            raise MappingError("invalid time origin")

    def local_step(self, global_step: int) -> int:
        value = self.local_origin + global_step - self.global_origin
        if value < 0:
            raise MappingError("global step precedes clock origin")
        return value

    def time_s(self, global_step: int) -> float:
        return self.time_origin_s + (global_step - self.global_origin) * self.dt_s

    def identity(self, global_step: int) -> tuple[int, int, float, int]:
        time_s = self.time_s(global_step)
        return global_step, self.local_step(global_step), time_s, canonical_tick(time_s)


@dataclass(frozen=True)
class MappingMatrix:
    """Sparse-free deterministic H matrix used for offline mapping checks."""

    weights: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if not self.weights or not self.weights[0]:
            raise MappingError("mapping matrix cannot be empty")
        width = len(self.weights[0])
        for row in self.weights:
            if len(row) != width or any(not math.isfinite(float(v)) for v in row):
                raise MappingError("mapping rows must have equal finite width")
            if abs(sum(row) - 1.0) > 1e-12:
                raise MappingError("consistent mapping rows must sum to one")

    @property
    def fluid_vertices(self) -> int:
        return len(self.weights)

    @property
    def structure_vertices(self) -> int:
        return len(self.weights[0])

    def consistent_displacement(self, structure_values: Sequence[Sequence[float]]) -> list[list[float]]:
        if len(structure_values) != self.structure_vertices:
            raise MappingError("structure displacement size mismatch")
        dimensions = len(structure_values[0])
        if dimensions == 0 or any(len(v) != dimensions for v in structure_values):
            raise MappingError("invalid displacement vectors")
        return [[sum(row[j] * structure_values[j][d] for j in range(self.structure_vertices)) for d in range(dimensions)] for row in self.weights]

    def conservative_force(self, fluid_values: Sequence[Sequence[float]]) -> list[list[float]]:
        if len(fluid_values) != self.fluid_vertices:
            raise MappingError("fluid force size mismatch")
        dimensions = len(fluid_values[0])
        if dimensions == 0 or any(len(v) != dimensions for v in fluid_values):
            raise MappingError("invalid force vectors")
        return [[sum(self.weights[i][j] * fluid_values[i][d] for i in range(self.fluid_vertices)) for d in range(dimensions)] for j in range(self.structure_vertices)]

    def virtual_work(self, structure_displacement: Sequence[Sequence[float]], fluid_force: Sequence[Sequence[float]]) -> tuple[float, float]:
        mapped = self.consistent_displacement(structure_displacement)
        conservative = self.conservative_force(fluid_force)
        lhs = sum(mapped[i][d] * fluid_force[i][d] for i in range(self.fluid_vertices) for d in range(len(mapped[i])))
        rhs = sum(structure_displacement[j][d] * conservative[j][d] for j in range(self.structure_vertices) for d in range(len(conservative[j])))
        return lhs, rhs
