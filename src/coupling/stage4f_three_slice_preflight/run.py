from __future__ import annotations

import json
import shutil
from pathlib import Path

from .campaign import PROJECT_ROOT, run_real_preflight


def main() -> int:
    protocol = PROJECT_ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2_1" / "three_slice_protocol_0_2_1.json"
    case_root = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_preflight" / "run_20260817_retry1"
    result_root = PROJECT_ROOT / "results" / "12_stage4f_three_slice_preflight"
    if case_root.exists():
        raise RuntimeError(f"refusing to reuse case root: {case_root}")
    if result_root.exists() and any(result_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite result root: {result_root}")
    result_root.mkdir(parents=True, exist_ok=True)
    summary = run_real_preflight(case_root, protocol, steps=3)
    for name in ("preflight_contract.json", "real_run_summary.json"):
        shutil.copy2(case_root / name, result_root / name)
    (result_root / "run_paths.json").write_text(json.dumps({"case_root": str(case_root), "result_root": str(result_root)}, indent=2), encoding="utf-8")
    return 0 if summary["status"] == "completed" else 2

if __name__ == "__main__":
    raise SystemExit(main())
