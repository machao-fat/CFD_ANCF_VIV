from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--Ur", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    module_path = Path(__file__).with_name("analyze_campaign.py")
    spec = importlib.util.spec_from_file_location("stage3_sdof_analysis", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load campaign analyzer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.analyze(args.audit, args.Ur)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
