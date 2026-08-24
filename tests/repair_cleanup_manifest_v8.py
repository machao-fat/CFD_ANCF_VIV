"""Remove any accidentally proposed OpenFOAM ``0`` time targets from the v8 manifest.

This is a manifest-only safety correction; it does not enumerate or delete
project files. The audit source also contains the permanent ``0`` protection.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(r"D:\研二文件\开题准备\CFD_ANCF_VIV").resolve()
CLEANUP = ROOT / "results" / "cleanup"


def main() -> None:
    manifest_path = CLEANUP / "delete_manifest_v8.csv"
    rows = list(csv.DictReader(manifest_path.open(encoding="utf-8-sig", newline="")))
    zero_rows = [row for row in rows if row.get("category") == "openfoam_time" and Path(row["absolute_path"]).name == "0"]
    if not all(Path(row["absolute_path"]).resolve().is_relative_to(ROOT) for row in rows):
        raise RuntimeError("manifest contains a path outside the project root")
    rows = [row for row in rows if row not in zero_rows]
    fields = ["absolute_path", "relative_path", "entry_type", "bytes", "reason", "regenerable_from", "stage_workload", "category", "reparse_checked"]
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    inventory_path = CLEANUP / "pre_cleanup_inventory_v8.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    groups: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["category"]].append(row)
    categories = [{"category": key, "count": len(value), "bytes": sum(int(row["bytes"]) for row in value)} for key, value in sorted(groups.items())]
    inventory["candidate_count"] = len(rows)
    inventory["candidate_bytes"] = sum(int(row["bytes"]) for row in rows)
    inventory["candidate_categories"] = categories
    inventory["audit_revision"] = "manifest-only correction: OpenFOAM 0 time directories are protected"
    inventory["protected_zero_time_candidates_removed"] = len(zero_rows)
    inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    candidate_gb = inventory["candidate_bytes"] / 1_000_000_000
    category_md = "\n".join(f"| {item['category']} | {item['count']} | {item['bytes']/1_000_000_000:.3f} GB |" for item in sorted(categories, key=lambda row: row["bytes"], reverse=True))
    (ROOT / "docs" / "cleanup_plan_v8.md").write_text(f"""# Project cleanup plan v8

The read-only audit found {inventory['logical_size_GB']:.3f} GB, {inventory['file_count']} files and {inventory['directory_count']} directories. The exact normalized deletion manifest contains {len(rows)} targets ({candidate_gb:.3f} GB logical size).

OpenFOAM `0`, `constant` and `system` are protected. A manifest-only safety correction removed {len(zero_rows)} accidentally proposed `0` time directories before execution. No project file was deleted.

| category | targets | bytes |
|---|---:|---:|
{category_md}

All targets are exact paths below the project root and are checked again by the single PowerShell deletion executor. Reparse points are not followed.
""", encoding="utf-8")
    (ROOT / "docs" / "cleanup_dry_run_v8.md").write_text(f"""# Cleanup dry-run v8

Status: **READY FOR REVIEWED EXECUTION**; no files were deleted.

- Candidate targets: {len(rows)}
- Estimated logical release: {candidate_gb:.3f} GB
- Protected `0` time directories removed from the manifest: {len(zero_rows)}
- Exact manifest: `results/cleanup/delete_manifest_v8.csv`
- Retain manifest: `results/cleanup/retain_manifest_v8.csv`
- Checkpoint hashes: `results/cleanup/stage3_v8_checkpoint_hash_manifest.json`
""", encoding="utf-8")
    print(json.dumps({"status": "manifest_corrected", "removed_zero_time_targets": len(zero_rows), "candidate_count": len(rows), "candidate_GB": round(candidate_gb, 3)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
