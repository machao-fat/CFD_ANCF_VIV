from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v3.audit import audit_result

parser = argparse.ArgumentParser()
parser.add_argument("--result", required=True)
parser.add_argument("--out-dir", required=True)
args = parser.parse_args()
gate = audit_result(Path(args.result).resolve(), Path(args.out_dir).resolve())
print(json.dumps(gate, ensure_ascii=True))
raise SystemExit(0 if gate["gate"].endswith(": pass") else 2)

