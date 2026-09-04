"""Fresh-runtime retry using strict terminal-quality observability."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
base_path = ROOT / "tools/stage375_cpp_worker_precice_three_slice_observability_040s_v1/run_stage375.py"
spec = importlib.util.spec_from_file_location("stage375_base", base_path)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load base runner")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.RUNTIME = ROOT / "runtime/stage377_cpp_worker_precice_three_slice_observability_040s_v1"
base.RESULTS = ROOT / "results/377_cpp_worker_precice_three_slice_observability_040s_v1"
base.QUALITY = ROOT / "tools/stage376_cpp_worker_precice_three_slice_observability_040s_v1/run_openfoam_with_metrics_v2.py"
base.STAGE_ID = "stage4f_d_cpp_worker_precice_three_slice_observability_040s_v1_retry2"
base.RUN_ID = "run377_cpp_worker_precice_three_slice_observability_040s_v1"
base.CASE_ID = "case377_cpp_worker_precice_three_slice_observability_040s_v1"


def main() -> int:
    cases = base.prepare()
    return_code, elapsed_s = base.launch(cases)
    gate = base.audit(cases, return_code, elapsed_s)
    print(base.json.dumps({"gate": gate["status"], "checks": gate["checks"], "elapsed_s": elapsed_s, "runtime": str(base.RUNTIME), "results": str(base.RESULTS)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
