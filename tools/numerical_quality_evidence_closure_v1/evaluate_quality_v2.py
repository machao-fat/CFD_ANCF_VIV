#!/usr/bin/env python3
"""Evaluate a read-only parsed OpenFOAM audit with a frozen V2 contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from coupling.openfoam_numerical_quality_contract_v2 import evaluate_quality


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = evaluate_quality(audit, contract)
    result["schema_version"] = "openfoam-numerical-quality-evaluation-v2"
    result["source_audit"] = str(args.audit)
    result["source_contract"] = str(args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
