from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--time", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.audit.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    candidates = [row for row in rows if math.isclose(float(row["time_s"]), args.time, rel_tol=0.0, abs_tol=1.0e-12)]
    if len(candidates) != 1:
        raise SystemExit(f"expected exactly one audit row at {args.time}, got {len(candidates)}")
    row = candidates[0]
    data = json.loads(args.template.read_text(encoding="utf-8"))
    step = int(float(row["step"]))
    time_s = float(row["time_s"])
    time_dir = args.case.resolve() / f"{time_s:g}"
    if not (time_dir / "U").is_file() or not (time_dir / "p").is_file():
        raise SystemExit(f"CFD synchronized time directory is missing: {time_dir}")
    data["state"] = {
        "a": float(row["ay_mps2"]), "v": float(row["vy_mps"]),
        "y": float(row["y_m"]), "step": step, "time_s": time_s,
    }
    data["interface_state_used_by_cfd"] = {
        "a": float(row["predicted_ay_mps2"]), "v": float(row["predicted_vy_mps"]),
        "y": float(row["predicted_y_m"]), "step": step, "time_s": time_s,
    }
    data["previous_force_y_N"] = float(row["force_y_N"])
    data["cumulative"] = {
        "fluid_work_structure_J": float(row["fluid_work_J"]),
        "fluid_work_cfd_predicted_J": float(row["fluid_work_cfd_predicted_J"]),
        "coupling_defect_work_J": float(row["coupling_defect_work_J"]),
        "damping_dissipation_J": float(row["damping_dissipation_J"]),
    }
    data["cfd"] = {"time_s": time_s, "time_directory": str(time_dir)}
    data["audit_row_count_this_segment"] = len(rows)
    data["recovered_from_audit"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "recovered", "step": step, "time_s": time_s, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
