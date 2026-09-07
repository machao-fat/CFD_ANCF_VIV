"""Repeat the frozen nonzero-motion diagnostic OFF/ON regression for patch 0005."""
from __future__ import annotations

from pathlib import Path

import run_diagnostic_off_on_regression as base


def main() -> int:
    base.RUN = "precice_time_layer_contract_v1_off_on_001"
    base.RUNTIME, base.RESULTS = base.ROOT / "runtime" / base.RUN, base.ROOT / "results" / base.RUN
    base.DIAG_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib"
    base.DIAG_UNC = Path(base.DIAG_WSL)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
