from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.coupling.online_file_coupling.continuous_fsi_driver import run_case


CASES = {
    "eb": ROOT / "cases" / "openfoam" / "single_slice_eb_transverse150_prepared",
    "ancf": ROOT / "cases" / "openfoam" / "single_slice_ancf_transverse150_prepared",
}


def require_s_ref_protocol_fix() -> None:
    publisher = ROOT / "tests" / "continuous_handshake" / "publish_load_from_forces.py"
    driver = ROOT / "src" / "coupling" / "online_file_coupling" / "continuous_fsi_driver.py"
    publisher_text = publisher.read_text(encoding="utf-8")
    driver_text = driver.read_text(encoding="utf-8")
    if '"--s-ref-m"' not in publisher_text or '"--s-ref-m"' not in driver_text:
        raise SystemExit(
            "REFUSING TO RUN: load s_ref_m is still hard-coded. Apply and test "
            "docs/04_s_ref_protocol_patch_proposal.md first."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one prepared 100-step transverse-only smoke case."
    )
    parser.add_argument("--branch", choices=("eb", "ancf"), required=True)
    parser.add_argument("--case", type=Path, help="Fresh case copy; defaults to the prepared branch case.")
    parser.add_argument("--end-step", type=int, default=100)
    parser.add_argument(
        "--results",
        type=Path,
        help="Fresh result directory; defaults to the branch-specific stage-three path.",
    )
    args = parser.parse_args()
    require_s_ref_protocol_fix()

    case = (args.case or CASES[args.branch]).resolve()
    if not case.is_dir():
        raise SystemExit(f"prepared case is missing: {case}")
    result = args.results or (
        ROOT
        / "results"
        / "04_eb_ancf_physical_comparison"
        / f"{args.branch}_online_transverse150_smoke"
    )
    if result.exists():
        raise SystemExit(f"refusing to reuse result directory: {result}")

    config = {
        "L": 150.0,
        "D": 1.0,
        "dInner": 0.9,
        "nElem": 10,
        "nSlices": 1,
        "s_ref_m": [75.0],
        "topTension_N": 1.0e6,
        "youngs_modulus_Pa": 2.07e11,
        "dt": 0.0025,
        "rayleigh_alpha": 0.019477603534520972,
        "rayleigh_beta": 0.0,
        "newton_tolerance": 1.0e-8,
    }
    outcome = run_case(
        branch=args.branch,
        case_dir=case,
        result_dir=result,
        end_step=args.end_step,
        dt=0.0025,
        config=config,
        load_mode="transverse_only",
        timeout_s=120.0,
    )
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()
