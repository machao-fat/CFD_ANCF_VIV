"""OFF/ON regression for the registry-safe diagnostic candidate."""
from __future__ import annotations

from pathlib import Path

import run_diagnostic_off_on_regression as base


def main() -> int:
    base.RUN = "of10_registry_safe_rollback_nonzero_motion_qualification_v1_off_on_001"
    base.RUNTIME, base.RESULTS = base.ROOT / "runtime" / base.RUN, base.ROOT / "results" / base.RUN
    base.DIAG_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_005/lib"
    base.DIAG_UNC = Path(base.DIAG_WSL)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
