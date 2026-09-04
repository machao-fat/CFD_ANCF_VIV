"""Fresh-runtime retry of the authorized 40-step observability window."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SCRIPT = ROOT / "tools/stage375_cpp_worker_precice_three_slice_observability_040s_v1/run_stage375.py"
SPEC = importlib.util.spec_from_file_location("stage375_runner_reused_only_as_code", SOURCE_SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load stage375 runner implementation")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

# Reuse only the audited launcher implementation, never its runtime/results.
BASE.RUNTIME = ROOT / "runtime/stage376_cpp_worker_precice_three_slice_observability_040s_v1"
BASE.RESULTS = ROOT / "results/376_cpp_worker_precice_three_slice_observability_040s_v1"
BASE.STAGE_ID = "stage4f_d_cpp_worker_precice_three_slice_observability_040s_v1_retry1"
BASE.RUN_ID = "run376_cpp_worker_precice_three_slice_observability_040s_v1"
BASE.CASE_ID = "case376_cpp_worker_precice_three_slice_observability_040s_v1"


def main() -> int:
    cases = BASE.prepare()
    return_code, elapsed_s = BASE.launch(cases)
    gate = BASE.audit(cases, return_code, elapsed_s)
    print(BASE.json.dumps({"gate": gate["status"], "checks": gate["checks"], "elapsed_s": elapsed_s, "runtime": str(BASE.RUNTIME), "results": str(BASE.RESULTS)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
