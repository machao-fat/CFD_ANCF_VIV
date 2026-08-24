from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v2.contracts import BenchmarkContract, FACTORS, canonical_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one bounded Stage95 benchmark contract.")
    parser.add_argument("--label", required=True, help="B, M, O, P, I, A, or FINAL")
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument("--source-step", type=int, required=True)
    parser.add_argument("--source-time", type=float, required=True)
    parser.add_argument("--source-tick", type=int, required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--coordinator-command", nargs=argparse.REMAINDER,
                        help="argv for the user-session coordinator; must be the final option")
    args = parser.parse_args()
    label = args.label.replace("+", "_").lower()
    run_id = f"stage95_{label}_{uuid.uuid4().hex[:12]}"
    case_id = f"stage95_case_{label}_{uuid.uuid4().hex[:8]}"
    source = Path(args.source_checkpoint).resolve()
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    factors = () if args.label == "B" else tuple(FACTORS) if args.label == "FINAL" else tuple(args.label.split("+"))
    contract = BenchmarkContract("stage95_performance_optimization_v2", run_id, case_id, Path(args.runtime),
        source, args.source_step, args.source_time, args.source_tick, source_checkpoint_sha256=source_sha,
        factors=factors)
    value = contract.to_dict(); value["configuration_label"] = args.label
    loop_dir = (ROOT / "src" / "coupling" / "performance_matlab_worker_bridge_v1").resolve().as_posix()
    runtime_expr = Path(args.runtime).resolve().as_posix().replace("'", "''")
    value["matlab_batch_command"] = f"addpath(genpath('{loop_dir}')); matlab_worker_loop('{runtime_expr}')"
    if args.coordinator_command:
        value["coordinator_command"] = list(args.coordinator_command)
    # Hash includes the label because it selects a distinct benchmark configuration.
    value["contract_sha256"] = __import__("hashlib").sha256(canonical_bytes({k: v for k, v in value.items() if k != "contract_sha256"})).hexdigest()
    output = Path(args.out).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{os.getpid()}.tmp"); temporary.write_bytes(canonical_bytes(value)); os.replace(temporary, output)
    print(json.dumps({"contract": str(output), "run_id": run_id, "case_id": case_id, "sha256": value["contract_sha256"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
