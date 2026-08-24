"""Incremental OpenFOAM CFL/health monitor used by the v2.3 pilot.

The monitor is deliberately line-oriented: incomplete log lines are retained for
the next read and only the registered solver is owned by the caller for cleanup.
"""

import math
import re


_TIME_RE = re.compile(r"^Time\s*=\s*(?P<time>[-+0-9.eE]+)")
_CFL_RE = re.compile(
    r"Courant Number mean:\s*(?P<mean>[-+0-9.eE]+)\s+max:\s*(?P<max>[-+0-9.eE]+)"
)


def parse_courant_line(line):
    """Return ``(mean, max)`` for a complete Courant line, else ``None``."""
    match = _CFL_RE.search(line)
    if not match:
        return None
    mean = float(match.group("mean"))
    maximum = float(match.group("max"))
    if not math.isfinite(mean) or not math.isfinite(maximum):
        raise ValueError("non-finite Courant number")
    return mean, maximum


def classify_log_line(line, hard_stop=0.8):
    """Classify one complete log line without treating partial lines as events."""
    cfl = parse_courant_line(line)
    if cfl is not None:
        return {"kind": "cfl", "mean": cfl[0], "max": cfl[1], "stop": cfl[1] >= hard_stop}
    upper = line.upper()
    if any(token in upper for token in ("FOAM FATAL", "FATAL ERROR", "SIGFPE")):
        return {"kind": "health", "stop": True, "reason": "solver_fatal"}
    if re.search(r"\b(?:NAN|INF)\b", upper):
        return {"kind": "health", "stop": True, "reason": "non_finite_solver_output"}
    if not line.endswith(("\n", "\r")) and line and not line.rstrip().endswith((";", ")")):
        return {"kind": "incomplete", "stop": False}
    return {"kind": "other", "stop": False}


class OnlineCFLMonitor:
    """Stateful incremental monitor; callers provide newly read complete lines."""

    def __init__(self, hard_stop=0.8):
        self.hard_stop = float(hard_stop)
        self.current_time = None
        self.events = []
        self.stop_reason = None

    def feed(self, line):
        time_match = _TIME_RE.search(line)
        if time_match:
            self.current_time = float(time_match.group("time"))
        event = classify_log_line(line, self.hard_stop)
        if event["kind"] == "cfl":
            event = dict(event)
            event["time"] = self.current_time
            self.events.append(event)
        if event.get("stop") and self.stop_reason is None:
            self.stop_reason = event.get("reason", "cfl_hard_stop")
        return event

    @property
    def should_stop(self):
        return self.stop_reason is not None

