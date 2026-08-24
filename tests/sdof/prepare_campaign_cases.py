from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--root-case", type=Path, required=True)
    parser.add_argument("--end-time", type=float, required=True)
    parser.add_argument("--ur", type=float, nargs="+", required=True)
    parser.add_argument("--suffix", default="v4")
    parser.add_argument("--write-interval", type=int, default=100)
    args = parser.parse_args()
    created = []
    for ur in args.ur:
        tag = str(ur).replace(".", "p")
        target = args.root_case / f"single_dof_free_viv_Ur{tag}_{args.suffix}"
        if target.exists():
            raise SystemExit(f"refusing to overwrite existing campaign case: {target}")
        shutil.copytree(args.template, target)
        coupling = target / "coupling"
        if coupling.exists():
            shutil.rmtree(coupling)
        coupling.mkdir(parents=True)
        (coupling / "consumed").mkdir()
        control = target / "system" / "controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^(\s*startFrom\s+).+;", r"\g<1>startTime;", text)
        text = re.sub(r"(?m)^(\s*startTime\s+).+;", r"\g<1>0;", text)
        text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{args.end_time:.12g};", text)
        text = re.sub(r"(?m)^(\s*writeInterval\s+).+;", rf"\g<1>{args.write_interval};", text, count=1)
        control.write_text(text, encoding="utf-8")
        (target / "campaign_preparation.json").write_text(json.dumps({
            "status": "fresh_case_from_same_30s_source_template",
            "Ur": ur, "end_time_s": args.end_time,
            "template": str(args.template.resolve()), "target": str(target.resolve()),
            "physical_parameters_changed": False, "field_write_interval_steps": args.write_interval,
        }, indent=2) + "\n", encoding="utf-8")
        created.append(str(target.resolve()))
    print(json.dumps({"created": created}, indent=2))


if __name__ == "__main__":
    main()
