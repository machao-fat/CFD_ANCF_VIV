"""Bounded, exact-PID OpenFOAM runner for v2.2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.coupling.process_control.process_limiter import ProcessLimiter
from src.coupling.stage4e_target_re_pilot_v2_1.runner_v2_1 import OwnedRunnerV21, closeout_process_audit, process_snapshot


class OwnedRunnerV22(OwnedRunnerV21):
    """Reuse the tested exact-PID runner, with v2.2 ownership metadata."""

    def execute(self, case_dir: Path, step: str, **kwargs: Any) -> dict[str, Any]:
        result = super().execute(case_dir, step, **kwargs)
        if self.registry:
            self.registry[-1]["purpose"] = f"v2.2 OpenFOAM {step} for {case_dir.name}"
            self._persist_registry()
        return result


def make_runner(runtime_root: Path, run_id: str, registry: list[dict[str, Any]]) -> tuple[ProcessLimiter, OwnedRunnerV22]:
    limiter = ProcessLimiter(1, run_id=run_id)
    return limiter, OwnedRunnerV22(limiter, registry, runtime_root, run_id)


__all__ = ["OwnedRunnerV22", "make_runner", "closeout_process_audit", "process_snapshot"]

