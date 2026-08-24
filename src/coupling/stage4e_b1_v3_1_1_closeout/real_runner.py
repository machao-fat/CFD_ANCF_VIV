from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.coupling.stage4e_b1_v3_1_closeout.real_runner import RealRunnerSession as _BaseRealRunnerSession


class RealRunnerSession(_BaseRealRunnerSession):
    """R2021b session isolated under the v3.1.1 runtime task."""

    def __init__(self, *, project_root: str | Path, config: Mapping[str, Any], matlab_exe: str | Path, purpose: str, runtime_task: str = "stage4e_b1_v3_1_1") -> None:
        super().__init__(project_root=project_root, config=config, matlab_exe=matlab_exe, purpose=purpose, runtime_task=runtime_task)
