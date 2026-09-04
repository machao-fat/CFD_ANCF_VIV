from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class _TimeRecord:
    time_s: float
    courant_max: float | None = None
    residual_max: float | None = None
    continuity_global: float | None = None
    iterations_max: int | None = None


class OpenFOAMLogParser:
    """Extract only solver-quality scalars from OpenFOAM stdout."""

    _time = re.compile(r"^\s*Time\s*=\s*([0-9.eE+-]+)")
    _courant = re.compile(r"Courant Number mean:\s*([0-9.eE+-]+)\s+max:\s*([0-9.eE+-]+)")
    _solve = re.compile(r"Solving for\s+[^,]+,\s*Initial residual\s*=\s*([0-9.eE+-]+),\s*Final residual\s*=\s*([0-9.eE+-]+),\s*No Iterations\s+(\d+)")
    _continuity = re.compile(r"continuity errors\s*:\s*sum local\s*=\s*([0-9.eE+-]+),\s*global\s*=\s*([0-9.eE+-]+)")

    def __init__(self) -> None:
        self._current: _TimeRecord | None = None
        self.records: list[dict[str, float | int]] = []

    def feed(self, line: str) -> None:
        match = self._time.search(line)
        if match:
            self._flush()
            self._current = _TimeRecord(float(match.group(1)))
            return
        if self._current is None:
            return
        match = self._courant.search(line)
        if match:
            self._current.courant_max = float(match.group(2))
            return
        match = self._solve.search(line)
        if match:
            final_residual = float(match.group(2))
            iterations = int(match.group(3))
            self._current.residual_max = max(self._current.residual_max or final_residual, final_residual)
            self._current.iterations_max = max(self._current.iterations_max or iterations, iterations)
            return
        match = self._continuity.search(line)
        if match:
            self._current.continuity_global = float(match.group(2))

    def _flush(self) -> None:
        if self._current is None:
            return
        item: dict[str, float | int] = {"time_s": self._current.time_s}
        for name in ("courant_max", "residual_max", "continuity_global", "iterations_max"):
            value = getattr(self._current, name)
            if value is not None:
                item[name] = value
        self.records.append(item)
        self._current = None

    def finalize(self) -> list[dict[str, float | int]]:
        self._flush()
        return list(self.records)
