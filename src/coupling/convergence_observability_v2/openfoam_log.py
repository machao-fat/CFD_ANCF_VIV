from __future__ import annotations

import math
import re
from dataclasses import dataclass


class OpenFOAMQualityError(ValueError):
    """Raised when a solver-quality record is incomplete or inconsistent."""


@dataclass
class _Record:
    time_s: float
    courant_max: float | None = None
    residual_max: float | None = None
    continuity_global: float | None = None
    iterations_max: int | None = None


class OpenFOAMQualityParser:
    """Parse one OpenFOAM log without retaining solver text.

    OpenFOAM prints the Courant line immediately before the next ``Time``
    marker.  A pending Courant value is therefore attached to that next
    time, including the startup value attached to the first time step.
    Residual and continuity values are collected after their Time marker.
    """

    _time = re.compile(r"^\s*Time\s*=\s*([0-9.eE+-]+)")
    _courant = re.compile(r"Courant Number mean:\s*([0-9.eE+-]+)\s+max:\s*([0-9.eE+-]+)")
    _solve = re.compile(r"Solving for\s+[^,]+,\s*Initial residual\s*=\s*([0-9.eE+-]+),\s*Final residual\s*=\s*([0-9.eE+-]+),\s*No Iterations\s+(\d+)")
    _continuity = re.compile(r"continuity errors\s*:\s*sum local\s*=\s*([0-9.eE+-]+),\s*global\s*=\s*([0-9.eE+-]+)")

    def __init__(self) -> None:
        self._current: _Record | None = None
        self._pending_courant: float | None = None
        self.records: list[dict[str, float | int]] = []

    @staticmethod
    def _finite(value: float, name: str) -> float:
        if not math.isfinite(value):
            raise OpenFOAMQualityError(f"{name} is NaN/Inf")
        return value

    def feed(self, line: str) -> None:
        match = self._courant.search(line)
        if match:
            self._pending_courant = self._finite(float(match.group(2)), "courant_max")
            return
        match = self._time.search(line)
        if match:
            self._flush()
            time_s = self._finite(float(match.group(1)), "time_s")
            self._current = _Record(time_s=time_s, courant_max=self._pending_courant)
            self._pending_courant = None
            return
        if self._current is None:
            return
        match = self._solve.search(line)
        if match:
            final = self._finite(float(match.group(2)), "residual_max")
            iterations = int(match.group(3))
            current = self._current
            current.residual_max = max(current.residual_max or final, final)
            current.iterations_max = max(current.iterations_max or iterations, iterations)
            return
        match = self._continuity.search(line)
        if match:
            self._current.continuity_global = self._finite(float(match.group(2)), "continuity_global")

    def _flush(self) -> None:
        if self._current is None:
            return
        if self._current.courant_max is None:
            raise OpenFOAMQualityError(f"missing Courant Number at time {self._current.time_s:g}")
        if self._current.residual_max is None:
            raise OpenFOAMQualityError(f"missing residual at time {self._current.time_s:g}")
        if self._current.continuity_global is None:
            raise OpenFOAMQualityError(f"missing continuity at time {self._current.time_s:g}")
        item: dict[str, float | int] = {"time_s": self._current.time_s,
                                        "courant_max": self._current.courant_max,
                                        "residual_max": self._current.residual_max,
                                        "continuity_global": self._current.continuity_global,
                                        "iterations_max": self._current.iterations_max or 0}
        self.records.append(item)
        self._current = None

    def finalize(self) -> list[dict[str, float | int]]:
        self._flush()
        if not self.records:
            raise OpenFOAMQualityError("no OpenFOAM time records")
        return list(self.records)
