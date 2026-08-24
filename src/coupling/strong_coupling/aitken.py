"""Bounded vector Aitken relaxation for fixed-point interface iterations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass
class AitkenRelaxer:
    omega: float = 0.2
    omega_min: float = 0.05
    omega_max: float = 0.8
    previous_residual: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if not (0.0 < self.omega_min <= self.omega_max):
            raise ValueError("Aitken bounds must be positive and ordered")
        self.omega = min(max(self.omega, self.omega_min), self.omega_max)
        self._initial_omega = self.omega

    def update(self, residual: Iterable[float]) -> float:
        current = tuple(float(v) for v in residual)
        if not current or any(not math.isfinite(v) for v in current):
            raise ValueError("Aitken residual must be finite and non-empty")
        if self.previous_residual is not None:
            if len(current) != len(self.previous_residual):
                raise ValueError("Aitken residual dimension changed")
            delta = tuple(a-b for a, b in zip(current, self.previous_residual))
            denominator = sum(v*v for v in delta)
            if denominator > 1.0e-30:
                # Dynamic vector Aitken relaxation:
                #   omega_k = -omega_(k-1) r_(k-1)^T (r_k-r_(k-1))
                #             / ||r_k-r_(k-1)||^2
                # The previous implementation used r_k in the numerator,
                # which differs by one full omega_(k-1) and is not the
                # standard fixed-point acceleration formula.
                numerator = sum(a*b for a, b in zip(self.previous_residual, delta))
                candidate = -self.omega*numerator/denominator
                if math.isfinite(candidate):
                    self.omega = min(max(candidate, self.omega_min), self.omega_max)
        self.previous_residual = current
        return self.omega

    def relax(self, old: tuple[float, ...] | list[float], raw: tuple[float, ...] | list[float]) -> tuple[float, ...]:
        if len(old) != len(raw):
            raise ValueError("Aitken state dimension changed")
        values = tuple(float(v) for v in old)
        target = tuple(float(v) for v in raw)
        if any(not math.isfinite(v) for v in values+target):
            raise ValueError("Aitken state must be finite")
        residual = tuple(t-o for o, t in zip(values, target))
        omega = self.update(residual)
        return tuple(o+omega*r for o, r in zip(values, residual))

    def reset(self, omega: float | None = None) -> None:
        """Reset iteration history at the start of a physical time step.

        A new physical step must not inherit the final relaxation factor from
        the previous step unless the caller explicitly supplies it.
        """
        requested = self._initial_omega if omega is None else float(omega)
        if not math.isfinite(requested):
            raise ValueError("Aitken reset omega must be finite")
        self.omega = min(max(requested, self.omega_min), self.omega_max)
        self.previous_residual = None
