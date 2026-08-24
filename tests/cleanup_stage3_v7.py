"""Read-only project-root cleanup audit for stage-three v7.

This script never deletes or archives anything.  It produces a complete file
inventory and conservative states; the subsequent archive/delete operation is
performed separately with literal, validated PowerShell paths.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"
OUT = RESULTS / "cleanup"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def state_for(path: Path, is_dir: bool) -> tuple[str, str, bool, str]:
    rel = path.relative_to(ROOT).as_posix()
    lower = rel.lower()
    if path == ROOT:
        return "DO_NOT_DELETE", "project root", False, "project root is never a cleanup target"
    if any(part in {".git", "src", "tests", "docs"} for part in path.relative_to(ROOT).parts):
        return "DO_NOT_DELETE", "critical source/test/documentation", True, "required for reproducibility and Stage-4 review"
    if lower.startswith("results/cleanup/") or lower.startswith("results/04_continuous_fsi/stage3_"):
        return "KEEP", "formal v7 audit/metrics", False, "current acceptance and cleanup evidence"
    if lower.startswith("results/04_sdof_corrected_campaign/asymptotic_v7/"):
        return "KEEP", "v7 asymptotic evidence", False, "required in final report and Stage-4 review"
    if lower.startswith("results/04_sdof_corrected_campaign/five_point_v6/"):
        return "KEEP", "final five-point data/figures", False, "retained final campaign evidence"
    if lower.endswith(".pyc") or "__pycache__" in lower:
        return "DELETE_REGENERABLE", "Python cache", True, "regenerable and not unique scientific evidence"
    if is_dir and any(token in path.name.lower() for token in ("retry", "failed", "smoke")):
        return "ARCHIVE_THEN_DELETE", "duplicate or failed intermediate candidate", True, "preserve a checksum archive before removal; verify no unique final evidence"
    if is_dir and path.name.replace(".", "", 1).isdigit() and path.parent.name.startswith("single_"):
        return "REVIEW_REQUIRED", "OpenFOAM numeric time directory", False, "may be required for restart or continuity; do not delete automatically"
    if lower.startswith("cases/"):
        return "REVIEW_REQUIRED", "OpenFOAM case asset", False, "case templates, checkpoints and runtime inputs require explicit retention review"
    if lower.startswith("results/"):
        return "REVIEW_REQUIRED", "result artifact", False, "could contain unique evidence; no automatic deletion"
    return "KEEP", "project artifact", False, "no safe regeneration/deletion proof"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    total = 0
    counts: dict[str, int] = {}
    bytes_by_state: dict[str, int] = {}
    for current, dirs, files in os.walk(ROOT, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(ROOT).as_posix().lower()
        retained_dirs = []
        for directory in sorted(dirs):
            candidate = current_path / directory
            candidate_relative = candidate.relative_to(ROOT).as_posix().lower()
            numeric_time = directory.replace(".", "", 1).isdigit() and candidate_relative.startswith("cases/openfoam/")
            if directory == "lnInclude" or directory == "consumed" or numeric_time or candidate.is_symlink():
                records.append({"absolute_path": str(candidate.absolute()), "relative_path": candidate_relative, "type": "directory_summary_only", "size_bytes": None, "state": "REVIEW_REQUIRED", "kind": "skipped high-volume/reparse directory", "regenerable": False, "unique_scientific_data": True, "generating_script": "not applicable", "stage4_impact": "explicit review required", "reason": "not expanded in file-level inventory to avoid following generated/reparse/high-volume trees"})
                continue
            retained_dirs.append(directory)
        dirs[:] = retained_dirs
        for name in sorted(files):
            path = current_path / name
            try:
                stat = path.lstat()
            except OSError as exc:
                records.append({"absolute_path": str(path.resolve()), "type": "unreadable", "error": str(exc), "state": "REVIEW_REQUIRED"})
                continue
            state, kind, regenerable, reason = state_for(path, False)
            item = {"absolute_path": str(path.absolute()), "relative_path": path.relative_to(ROOT).as_posix(), "type": "file", "size_bytes": stat.st_size, "state": state, "kind": kind, "regenerable": regenerable, "unique_scientific_data": not regenerable, "generating_script": "unknown; inspect artifact metadata before deletion", "stage4_impact": "retain unless archived and proven duplicate", "reason": reason, "sha256": "not_computed_in_read_only_inventory; archive candidates are hashed before deletion"}
            records.append(item)
            total += stat.st_size
            counts[state] = counts.get(state, 0) + 1
            bytes_by_state[state] = bytes_by_state.get(state, 0) + stat.st_size
    payload = {
        "schema_version": "cleanup_inventory_v7",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT.resolve()),
        "scope": "project root only; no sibling directories, Zotero storage or other projects",
        "read_only_audit": True,
        "file_count": len(records), "total_size_bytes": total,
        "counts_by_state": counts, "bytes_by_state": bytes_by_state,
        "records": records,
    }
    (OUT / "cleanup_inventory_v7.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Stage-3 v7 cleanup read-only audit", "", f"- project root: `{ROOT}`", "- audit is read-only; no files were archived or deleted", f"- files: {len(records)}", f"- total size: {total / 1024**3:.3f} GiB", "", "| state | files | size (GiB) |", "|---|---:|---:|"]
    for state in sorted(counts):
        lines.append(f"| {state} | {counts[state]} | {bytes_by_state[state] / 1024**3:.3f} |")
    lines += ["", "## Safety rule", "", "Only exact absolute paths inside the project root may be archived/deleted after explicit retention review. The project root itself, source, tests, formal docs, v7 JSON/figures, final campaign data, OpenFOAM templates/checkpoints and restart evidence are retained. Any uncertain numeric OpenFOAM time directory is REVIEW_REQUIRED."]
    (DOCS / "cleanup_audit_v7.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"file_count": len(records), "total_size_bytes": total, "counts_by_state": counts, "bytes_by_state": bytes_by_state}, indent=2))


if __name__ == "__main__":
    main()
