"""Terminal force-file audit for the restart campaign.

OpenFOAM may flush ``forces.dat`` after the exact target row has been
consumed but before the owned solver exits.  Refreshing the fingerprint is
valid only when the terminal file still contains exactly one identical target
row.  The production process and driver modules remain unchanged.
"""
from __future__ import annotations

from typing import Any

from ..multi_slice_driver.real_process import (
    RealProcessFreshnessError, _FORCE_RE, fingerprint, parse_force_exact, time_close,
)
from ..stage4f_c_predictor_consistent_strong_v2.iteration_engine import (
    CandidateIterationEngine as PredictorConsistentCandidateIterationEngine,
)


def refresh_terminal_force(process: Any, *, time_s: float) -> None:
    """Bind the consumed force identity to the terminal file fingerprint."""
    consumed = process.last_force
    if consumed is None:
        raise RealProcessFreshnessError("terminal audit requires a consumed force row")
    if process.process is None:
        raise RealProcessFreshnessError("terminal audit requires an owned solver process")
    code = process.process.wait(timeout=process.runtime_config.timeout_s)
    if code != 0:
        raise RuntimeError(f"slice {process.slice_id} OpenFOAM returned {code}")
    terminal = parse_force_exact(process._force_path(time_s), target_time_s=time_s)
    if terminal is None:
        raise RealProcessFreshnessError("terminal force file lacks one unique target row")
    if not time_close(terminal.time_s, consumed.time_s, 1.0e-12) or terminal.force_N != consumed.force_N:
        raise RealProcessFreshnessError("terminal force row differs from consumed force row")
    text = process._force_path(time_s).read_text(encoding="utf-8", errors="strict")
    later_times = []
    for line in text.splitlines():
        match = _FORCE_RE.match(line)
        if match:
            value = float(match.group(1))
            if value > time_s + 1.0e-12:
                later_times.append(value)
    if later_times:
        raise RealProcessFreshnessError("terminal force file contains data later than the target time")
    process.last_force = terminal
    process.last_force_fingerprint = fingerprint(process._force_path(time_s))


class CandidateIterationEngine(PredictorConsistentCandidateIterationEngine):
    """Predictor-consistent engine with terminally stable force fingerprints."""

    def _finish_slice_processes(self) -> None:
        if getattr(self, "_processes_finished", False):
            return
        for process in self.processes:
            refresh_terminal_force(process, time_s=self.target_time_s)
            process.finish_step(self.physical_step, self.target_time_s)
        self._snapshot_processes()
        self._processes_finished = True


def candidate_factory(plan):
    engine = CandidateIterationEngine(plan)
    return engine, engine.shutdown
