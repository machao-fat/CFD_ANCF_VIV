from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from pathlib import Path


def numeric_times(case: Path) -> list[float]:
    values = []
    for item in case.iterdir():
        if item.is_dir():
            try:
                values.append(float(item.name))
            except ValueError:
                pass
    return sorted(values)


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    return "/mnt/" + resolved.drive[0].lower() + str(resolved).replace("\\", "/")[2:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--time", type=float, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    saved = numeric_times(args.case)
    records = []
    for requested in args.time:
        if not saved:
            records.append({"requested_time_s": requested, "status": "no_saved_time_directory"})
            continue
        selected = min(saved, key=lambda value: abs(value - requested))
        command = f"source /opt/openfoam10/etc/bashrc; cd {wsl_path(args.case)!r}; checkMesh -time {selected:g}"
        completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command], capture_output=True, text=True, errors="replace", timeout=120)
        text = completed.stdout + "\n" + completed.stderr
        def number(pattern: str) -> float | None:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            return float(match.group(1)) if match else None
        numeric = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
        min_volume = number(rf"Min volume\s*=\s*({numeric})")
        non_orth = number(rf"Non-orthogonality Max:\s*({numeric})")
        skewness = number(rf"Max skewness\s*=\s*({numeric})")
        failed = number(r"Failed\s+(\d+)\s+mesh checks")
        operational = (
            completed.returncode == 0 and min_volume is not None and min_volume > 0.0
            and non_orth is not None and non_orth < 65.0
            and skewness is not None and skewness < 4.0
        )
        records.append({
            "requested_time_s": requested, "checked_time_s": selected,
            "checkMesh_exit_code": completed.returncode,
            "min_volume_m3": min_volume, "max_non_orthogonality_deg": non_orth,
            "max_skewness": skewness, "reported_failed_checks": int(failed) if failed is not None else None,
            "operational_mesh_safety_pass": operational,
            "note": "OpenFOAM directional-alignment warning is retained if reported; volume/non-orthogonality/skewness thresholds are the operational safety gate.",
        })
    payload = {
        "case": str(args.case.resolve()), "requested_times_s": args.time,
        "records": records, "all_operational_mesh_safety_pass": all(item.get("operational_mesh_safety_pass", False) for item in records),
        "thresholds": {"min_volume_m3": ">0", "max_non_orthogonality_deg": "<65", "max_skewness": "<4"},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case": str(args.case), "all_operational_mesh_safety_pass": payload["all_operational_mesh_safety_pass"], "records": len(records)}, indent=2))


if __name__ == "__main__":
    main()
