"""Exact-PID runner for the isolated v2.2.2 cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.coupling.process_control.process_limiter import ProcessLimiter
from src.coupling.stage4e_target_re_pilot_v2_2_1.runner_v2_2_1 import (
    OwnedRunnerV221,
    closeout_process_audit,
    process_snapshot,
)


class OwnedRunnerV222(OwnedRunnerV221):
    def execute(self, case_dir: Path, step: str, **kwargs: Any) -> dict[str, Any]:
        result = super().execute(case_dir, step, **kwargs)
        if self.registry:
            self.registry[-1]["purpose"] = f"v2.2.2 OpenFOAM {step} for {case_dir.name}"
            self._persist_registry()
        return result


def make_runner(runtime_root: Path, run_id: str, registry: list[dict[str, Any]]) -> tuple[ProcessLimiter, OwnedRunnerV222]:
    limiter = ProcessLimiter(1, run_id=run_id)
    return limiter, OwnedRunnerV222(limiter, registry, runtime_root, run_id)


__all__ = ["OwnedRunnerV222", "make_runner", "closeout_process_audit", "process_snapshot"]
