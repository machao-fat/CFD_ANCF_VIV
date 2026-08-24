from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v2.attribution import attribute_measurements


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("measurements")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = attribute_measurements(json.loads(Path(args.measurements).read_text(encoding="utf-8"))).to_dict()
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
