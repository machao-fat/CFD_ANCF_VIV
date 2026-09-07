"""Run the existing nonzero prescribed-motion fixture against diagnostic build .004."""
from __future__ import annotations

from pathlib import Path

import run_diagnostic_off_on_regression as base


def main() -> int:
    base.RUN = "openfoam10_checkpoint_lifecycle_motion_timing_closure_v1_off_on_003"
    base.RUNTIME, base.RESULTS = base.ROOT / "runtime" / base.RUN, base.ROOT / "results" / base.RUN
    base.DIAG_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_004/lib"
    # The runner executes inside WSL, so use the native POSIX library path.
    base.DIAG_UNC = Path(base.DIAG_WSL)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
