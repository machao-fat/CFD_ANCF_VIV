"""Stage-local terminal force audit requiring the target to be the last row."""
from __future__ import annotations

import math
from typing import Any

from ..multi_slice_driver import real_process
from ..stage4f_c_restart_extended_v1.force_terminal_audit_repair import CandidateIterationEngine as BaseEngine


def refresh_terminal_force(process: Any, *, time_s: float) -> None:
    consumed = process.last_force
    if consumed is None or process.process is None:
        raise real_process.RealProcessFreshnessError("terminal audit lacks consumed force or owned process")
    code = process.process.wait(timeout=process.runtime_config.timeout_s)
    if code != 0:
        raise RuntimeError(f"slice {process.slice_id} OpenFOAM returned {code}")
    path = process._force_path(time_s)
    terminal = real_process.parse_force_exact(path, target_time_s=time_s)
    if terminal is None:
        raise real_process.RealProcessFreshnessError("terminal force file lacks one unique target row")
    numeric_times = []
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        match = real_process._FORCE_RE.match(line)
        if match:
            value = float(match.group(1))
            if not math.isfinite(value):
                raise real_process.RealProcessFreshnessError("forces.dat contains NaN/Inf time")
            numeric_times.append(value)
    if not numeric_times or not real_process.time_close(numeric_times[-1], terminal.time_s, 1e-12):
        raise real_process.RealProcessFreshnessError("target force is not the last complete numeric row")
    if not real_process.time_close(terminal.time_s, consumed.time_s, 1e-12) or terminal.force_N != consumed.force_N:
        raise real_process.RealProcessFreshnessError("terminal force row differs from consumed force row")
    process.last_force = terminal
    process.last_force_fingerprint = real_process.fingerprint(path)


class CandidateIterationEngine(BaseEngine):
    def _finish_slice_processes(self) -> None:
        if getattr(self, "_processes_finished", False):
            return
        for process in self.processes:
            refresh_terminal_force(process, time_s=self.target_time_s)
            process.finish_step(self.physical_step, self.target_time_s)
        self._snapshot_processes()
        self._processes_finished = True
