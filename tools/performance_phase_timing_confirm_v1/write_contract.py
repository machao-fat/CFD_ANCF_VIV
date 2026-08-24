from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v2.contracts import contract_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default="performance_phase_timing_confirm_001")
    parser.add_argument("--case-id", default="performance_phase_timing_case_001")
    args = parser.parse_args()
    template = Path(args.template).resolve()
    value = json.loads(template.read_text(encoding="utf-8"))
    value.update({
        "stage_id": "stage4f_d_performance_phase_timing_confirm_v1",
        "run_id": str(args.run_id), "case_id": str(args.case_id),
        "runtime": str(Path(args.runtime).resolve()),
        "phase_timing_confirm": True,
        "no_retry": True,
        "steps": 40, "segment_duration_s": 0.05, "slice_count": 3,
        "scope": {"no_statistics": True, "no_e5c": True, "no_five_slice": True,
                  "no_nine_slice": True, "no_long_time_viv": True,
                  "no_lock_in": True, "no_experiment": True},
    })
    bridge = (ROOT / "src" / "coupling" / "performance_matlab_worker_bridge_v1").resolve().as_posix()
    runtime_expr = Path(args.runtime).resolve().as_posix()
    value["matlab_batch_command"] = f"addpath(genpath('{bridge}')); matlab_worker_loop('{runtime_expr}')"
    value.pop("contract_sha256", None)
    value["contract_sha256"] = contract_hash(value)
    output = Path(args.out).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps({"contract": str(output), "contract_sha256": value["contract_sha256"],
                      "run_id": value["run_id"], "case_id": value["case_id"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
