"""Incremental, line-safe Courant-number monitoring for pimpleFoam logs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
COURANT_RE = re.compile(
    r"Courant Number mean:\s*(?P<mean>" + NUMBER + r")\s*max:\s*(?P<max>" + NUMBER + r")"
)
TIME_RE = re.compile(r"(?:^|\n)Time\s*=\s*(?P<time>" + NUMBER + r")")


@dataclass
class IncrementalCFLMonitor:
    """Parse only complete log lines and stop exactly at the hard limit."""

    hard_limit: float = 0.8
    _pending: str = ""
    _offset: int = 0
    _current_time_s: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    stopped: bool = False
    stop_reason: str | None = None

    def feed(self, chunk: str) -> dict[str, Any] | None:
        if not isinstance(chunk, str):
            raise TypeError("CFL monitor accepts text chunks")
        text = self._pending + chunk
        lines = text.splitlines(keepends=True)
        self._pending = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self._pending = lines.pop()
        for line in lines:
            time_match = TIME_RE.search(line)
            if time_match:
                self._current_time_s = float(time_match.group("time"))
                if not math.isfinite(self._current_time_s):
                    return self._stop("non_finite_time", self._current_time_s)
            c_match = COURANT_RE.search(line)
            if "Courant Number" in line and re.search(r"(?:nan|inf|infinity)", line, flags=re.IGNORECASE):
                return self._stop("non_finite_cfl", self._current_time_s)
            if not c_match:
                continue
            mean = float(c_match.group("mean"))
            maximum = float(c_match.group("max"))
            event = {
                "time_s": self._current_time_s,
                "mean_cfl": mean,
                "max_cfl": maximum,
            }
            self.events.append(event)
            if not (math.isfinite(mean) and math.isfinite(maximum)):
                return self._stop("non_finite_cfl", self._current_time_s, event)
            if maximum >= self.hard_limit:
                return self._stop("max_cfl_ge_0.8", self._current_time_s, event)
        return None

    def flush(self) -> dict[str, Any] | None:
        """Incomplete trailing lines are deliberately not interpreted."""
        self._pending = ""
        return None

    def _stop(self, reason: str, time_s: float | None, event: dict[str, Any] | None = None) -> dict[str, Any]:
        self.stopped = True
        self.stop_reason = reason
        result = {"reason": reason, "time_s": time_s}
        if event is not None:
            result["event"] = event
        return result

    def summary(self) -> dict[str, Any]:
        maxima = [float(item["max_cfl"]) for item in self.events if math.isfinite(float(item["max_cfl"]))]
        means = [float(item["mean_cfl"]) for item in self.events if math.isfinite(float(item["mean_cfl"]))]
        return {
            "hard_stop_threshold": self.hard_limit,
            "samples": len(self.events),
            "max_cfl": max(maxima) if maxima else None,
            "mean_cfl_max": max(means) if means else None,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "stop_time_s": next((item.get("time_s") for item in reversed(self.events) if item.get("max_cfl", -1) >= self.hard_limit), None),
            "events": list(self.events),
        }


def monitor_log_increment(log_path: str, monitor: IncrementalCFLMonitor) -> dict[str, Any] | None:
    """Read one newly appended block from a UTF-8 solver log."""
    from pathlib import Path

    path = Path(log_path)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        stream.seek(monitor._offset)
        chunk = stream.read()
        monitor._offset = stream.tell()
    return monitor.feed(chunk) if chunk else None
