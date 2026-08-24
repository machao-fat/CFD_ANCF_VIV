"""CLI for freeze/preflight/closeout; solver execution stays explicit in-process."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json
from .real_runner import freeze, preflight, process_closeout
from .execute import execute_diagnostic


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze"); p.add_argument("--output", type=Path, required=True); p.add_argument("--parent", type=Path, required=True); p.add_argument("--protection-sha256", required=True)
    p = sub.add_parser("preflight"); p.add_argument("--contract", type=Path, required=True); p.add_argument("--branch", choices=("D1","D2"), required=True); p.add_argument("--case-root", type=Path, required=True); p.add_argument("--runtime-root", type=Path, required=True); p.add_argument("--results-root", type=Path, required=True); p.add_argument("--parent", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run"); p.add_argument("--branch", choices=("D1","D2"), required=True); p.add_argument("--preflight", type=Path, required=True); p.add_argument("--engine-factory", required=True, help="module:function returning (run_one_step, shutdown_owned)"); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("closeout"); p.add_argument("--registry", type=Path, required=True); p.add_argument("--residual", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze": value = freeze(output=args.output, parent_checkpoint=args.parent, parent_protection_sha256=args.protection_sha256)
    elif args.command == "preflight":
        value = preflight(contract_path=args.contract, branch=args.branch, case_root=args.case_root, runtime_root=args.runtime_root, results_root=args.results_root, parent_checkpoint=args.parent); atomic_write_json(args.output,value)
    elif args.command == "run":
        checked=json.loads(args.preflight.read_text(encoding="utf-8"))
        if checked.get("status") != "passed" or checked.get("branch") != args.branch: raise RuntimeError("preflight does not authorize this branch")
        module_name,function_name=args.engine_factory.split(":",1); factory=getattr(importlib.import_module(module_name),function_name)
        run_one_step,shutdown_owned=factory(checked["plan"]); value=execute_diagnostic(args.branch,run_one_step,shutdown_owned); atomic_write_json(args.output,value)
    else:
        records=json.loads(args.registry.read_text(encoding="utf-8")); residual=json.loads(args.residual.read_text(encoding="utf-8")); value=process_closeout(records,residual_identities=residual); atomic_write_json(args.output,value)
    print(json.dumps(value, ensure_ascii=False)); return 0 if value.get("status", "passed") == "passed" and value.get("passed", True) else 2


if __name__ == "__main__": raise SystemExit(main())
