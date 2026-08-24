from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v3.contracts import make_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--case-id")
    parser.add_argument("--matlab-executable", default=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
    parser.add_argument("--no-native-staging", action="store_true")
    parser.add_argument("--checkpoint-hash-cache", action="store_true")
    parser.add_argument("--disable-force-coeffs", action="store_true")
    parser.add_argument("--openfoam-poll-interval", type=float, default=0.001)
    parser.add_argument("--compact-force-snapshot", action="store_true")
    parser.add_argument("--protocol-poll-interval", type=float, default=0.001)
    parser.add_argument("--field-write-format", choices=("ascii", "binary"), default="ascii")
    parser.add_argument("--direct-wsl-exec", action="store_true")
    parser.add_argument("--field-write-precision", type=int, default=16)
    parser.add_argument("--ephemeral-exchange-io", action="store_true")
    parser.add_argument("--prewarm-openfoam-startup", action="store_true")
    parser.add_argument("--reuse-parallel-executor", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id or f"stage96_v3_mop_{uuid.uuid4().hex[:12]}"
    case_id = args.case_id or f"stage96_case_mop_{uuid.uuid4().hex[:10]}"
    value = make_contract(project_root=ROOT, runtime=Path(args.runtime).resolve(),
                          source_checkpoint=Path(args.source_checkpoint).resolve(),
                          run_id=run_id, case_id=case_id, matlab_executable=args.matlab_executable,
                          wsl_native_case_staging=not args.no_native_staging,
                          native_checkpoint_direct=False if args.no_native_staging else True,
                          checkpoint_hash_cache=args.checkpoint_hash_cache,
                          disable_force_coeffs_output=args.disable_force_coeffs,
                          openfoam_poll_interval_s=args.openfoam_poll_interval,
                          compact_force_snapshot=args.compact_force_snapshot,
                          protocol_poll_interval_s=args.protocol_poll_interval,
                          field_write_format=args.field_write_format,
                          direct_wsl_exec=args.direct_wsl_exec,
                          field_write_precision=args.field_write_precision,
                          ephemeral_exchange_io=args.ephemeral_exchange_io,
                          prewarm_openfoam_startup=args.prewarm_openfoam_startup,
                          reuse_parallel_executor=args.reuse_parallel_executor)
    output = Path(args.out).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"run_id": run_id, "case_id": case_id, "contract": str(output), "contract_sha256": value["contract_sha256"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
