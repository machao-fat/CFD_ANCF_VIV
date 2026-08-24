from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--mesh", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    payload = json.loads(args.metrics.read_text(encoding="utf-8"))
    records = []
    for path in args.mesh:
        data = json.loads(path.read_text(encoding="utf-8"))
        records.extend(data["records"])
    lookup = {round(float(item["requested_time_s"]), 9): item for item in records}
    for block in payload["blocks_5p2s"]:
        record = lookup.get(round(float(block["end_s"]), 9))
        if record is None:
            block["mesh_safety_status"] = "not_audited"
        else:
            block["mesh_safety_status"] = "pass" if record["operational_mesh_safety_pass"] else "fail"
            block["mesh_check_time_s"] = record.get("checked_time_s")
            block["mesh_min_volume_m3"] = record.get("min_volume_m3")
            block["mesh_max_non_orthogonality_deg"] = record.get("max_non_orthogonality_deg")
            block["mesh_max_skewness"] = record.get("max_skewness")
    payload["mesh_audit_files"] = [str(path.resolve()) for path in args.mesh]
    payload["mesh_audit_summary"] = {
        "records": len(records), "all_operational_mesh_safety_pass": all(item.get("operational_mesh_safety_pass", False) for item in records),
        "thresholds": {"min_volume_m3": ">0", "max_non_orthogonality_deg": "<65", "max_skewness": "<4"},
    }
    args.metrics.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["mesh_audit_summary"], indent=2))


if __name__ == "__main__":
    main()
