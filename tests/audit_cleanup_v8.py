"""Fast, non-destructive v8 project cleanup audit.

This script only inventories files, hashes retained evidence and writes an
exact deletion manifest.  Permanent deletion is deliberately implemented in
the separate PowerShell executor so all destructive operations use one
PowerShell process.
"""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(r"D:\研二文件\开题准备\CFD_ANCF_VIV").resolve()
CLEANUP = ROOT / "results" / "cleanup"
CASES = ROOT / "cases" / "openfoam"
PREFIX = str(ROOT).casefold() + os.sep
REPARSE_FLAG = 0x400
CACHE_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dynamicCode"}
FILE_PATTERNS = ("*.pyc", "*.pyo", "*.o", "*.dep", "*.bak", "*.tmp", "*.temp", "*.swp", "*.swo", "*.dmp", "*.tif", "*.tiff")
NUMERIC_TIME = re.compile(r"^\d+(?:\.\d+)?$")
KEY_CASE = re.compile(r"Ur4|Ur5p2|Ur6|Ur7p1|Ur8|single_slice_(?:eb|ancf)", re.IGNORECASE)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def inside(path: Path) -> bool:
    value = str(path.resolve()).casefold()
    return value.startswith(PREFIX) and value != str(ROOT).casefold()


def is_reparse(stat_result: os.stat_result) -> bool:
    return bool(getattr(stat_result, "st_file_attributes", 0) & REPARSE_FLAG)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def file_hash_records(paths: list[tuple[str, Path]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for label, path in paths:
        path = path.resolve()
        if not inside(path) and path != ROOT:
            raise RuntimeError(f"hash path outside project: {path}")
        if path.is_file():
            records.append({"label": label, "relative_path": rel(path), "absolute_path": str(path), "status": "present", "bytes": path.stat().st_size, "sha256": sha256(path)})
        else:
            records.append({"label": label, "relative_path": rel(path), "absolute_path": str(path), "status": "missing", "bytes": 0, "sha256": None})
    return records


def walk() -> dict[str, object]:
    if not ROOT.is_dir() or ROOT.parent != Path(r"D:\研二文件\开题准备"):
        raise RuntimeError(f"unexpected project root: {ROOT}")
    stack = [ROOT]
    file_count = 0
    directory_count = 0
    logical_bytes = 0
    dir_sizes: dict[str, int] = {str(ROOT): 0}
    extension_bytes: defaultdict[str, int] = defaultdict(int)
    reparse_points: list[str] = []
    candidates: list[dict[str, object]] = []
    top_files: list[dict[str, object]] = []
    case_root = str(CASES.resolve()).casefold()
    results_root = str((ROOT / "results").resolve()).casefold()
    while stack:
        current = Path(stack.pop())
        current_key = str(current).casefold()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    # Do not call Path.resolve() before checking reparse
                    # attributes: OpenFOAM lnInclude contains symlink-like
                    # entries that must be recorded and skipped, never followed.
                    path = Path(os.path.abspath(entry.path))
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise RuntimeError(f"cannot stat {path}: {exc}") from exc
                    if is_reparse(stat_result):
                        reparse_points.append(str(path))
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        directory_count += 1
                        dir_sizes.setdefault(str(path), 0)
                        stack.append(str(path))
                        name = entry.name
                        if name in CACHE_NAMES and not str(path).casefold().startswith(str(ROOT / ".git").casefold()):
                            candidates.append({"absolute_path": str(path), "entry_type": "directory", "reason": f"rebuildable cache directory {name}", "regenerable_from": "Python/pytest/OpenFOAM build tools", "stage_workload": "all", "category": "cache", "bytes": 0})
                        if re.fullmatch(r"processor\d+", name, flags=re.IGNORECASE):
                            candidates.append({"absolute_path": str(path), "entry_type": "directory", "reason": "rebuildable OpenFOAM processor decomposition", "regenerable_from": "decomposePar/reconstructPar", "stage_workload": "CFD", "category": "processor", "bytes": 0})
                        parent = path.parent
                        if str(current.parent).casefold() == case_root and NUMERIC_TIME.fullmatch(name):
                            candidates.append({"absolute_path": str(path), "entry_type": "directory", "entry_subtype": "openfoam_time", "case_name": current.name, "time_name": name, "reason": "intermediate OpenFOAM time directory", "regenerable_from": "case 0/constant/system plus retained checkpoint and final CSV/JSON", "stage_workload": "CFD", "category": "openfoam_time", "bytes": 0})
                        continue
                    size = int(stat_result.st_size)
                    file_count += 1
                    logical_bytes += size
                    suffix = path.suffix.lower() or "<none>"
                    extension_bytes[suffix] += size
                    parent = path.parent
                    while True:
                        parent_key = str(parent)
                        dir_sizes[parent_key] = dir_sizes.get(parent_key, 0) + size
                        if parent == ROOT:
                            break
                        if not str(parent).casefold().startswith(str(ROOT).casefold()):
                            raise RuntimeError(f"parent escaped root for {path}")
                        parent = parent.parent
                    if len(top_files) < 2000:
                        top_files.append({"path": str(path), "bytes": size})
                    else:
                        minimum = min(item["bytes"] for item in top_files)
                        if size > minimum:
                            top_files.append({"path": str(path), "bytes": size})
                            top_files = sorted(top_files, key=lambda item: int(item["bytes"]), reverse=True)[:1000]
                    name = entry.name
                    if str(path).casefold().startswith(str(ROOT / ".git").casefold()):
                        continue
                    for pattern in FILE_PATTERNS:
                        if fnmatch.fnmatchcase(name.lower(), pattern):
                            if pattern in ("*.tif", "*.tiff") and not str(path).casefold().startswith(results_root + os.sep):
                                continue
                            category = "old_figure" if pattern in ("*.tif", "*.tiff") else "build_artifact" if pattern in ("*.o", "*.dep") else "temporary_file"
                            candidates.append({"absolute_path": str(path), "entry_type": "file", "reason": f"rebuildable file matching {pattern}", "regenerable_from": "source code, plotting script or compiler", "stage_workload": "all", "category": category, "bytes": size})
                            break
        except OSError as exc:
            raise RuntimeError(f"cannot enumerate {current}: {exc}") from exc
    top_dirs = [{"path": path, "bytes": int(size)} for path, size in sorted(dir_sizes.items(), key=lambda item: item[1], reverse=True)[:50]]
    return {"logical_bytes": logical_bytes, "file_count": file_count, "directory_count": directory_count, "dir_sizes": dir_sizes, "extension_bytes": dict(sorted(extension_bytes.items(), key=lambda item: item[1], reverse=True)), "reparse_points": reparse_points, "candidates": candidates, "top_files": sorted(top_files, key=lambda item: int(item["bytes"]), reverse=True)[:100], "top_directories": top_dirs}


def build_candidates(summary: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    seeds = list(summary["candidates"])
    time_by_case: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for item in seeds:
        if item.get("entry_subtype") == "openfoam_time":
            time_by_case[str(item["case_name"])].append(item)
    retained_time: list[dict[str, object]] = []
    selected: dict[str, dict[str, object]] = {}
    for item in seeds:
        path = Path(str(item["absolute_path"])).resolve()
        if not inside(path):
            raise RuntimeError(f"candidate outside root: {path}")
        if item.get("entry_subtype") == "openfoam_time":
            siblings = time_by_case[str(item["case_name"])]
            latest = max(siblings, key=lambda row: float(str(row["time_name"])))
            # OpenFOAM's 0 time directory is a required base state and is
            # never a deletion candidate, regardless of the latest time.
            keep = str(item["time_name"]) in {"0", str(latest["time_name"])}
            case_name = str(item["case_name"])
            time_name = str(item["time_name"])
            if re.search(r"Ur5p2_v8_dt0025_from130|Ur5p2_v8_dt00125_from130", case_name) and time_name in {"130", "150"}:
                keep = True
            if re.search(r"Ur5p2_v6_retry_to130", case_name) and time_name == "130":
                keep = True
            if re.search(r"Ur8", case_name, flags=re.IGNORECASE) and time_name == "240":
                keep = True
            if re.search(r"Ur4", case_name, flags=re.IGNORECASE) and time_name == "140":
                keep = True
            reason = f"intermediate OpenFOAM time directory; latest/key time retained ({latest['time_name']})"
            item = dict(item)
            item["reason"] = reason
            if keep:
                retained_time.append({"relative_path": rel(path), "absolute_path": str(path), "entry_type": "case_checkpoint_or_latest", "bytes": int(summary["dir_sizes"].get(str(path), 0)), "reason": "retained 0/constant/system plus latest or explicitly required checkpoint", "required_for": "restart and stage3 evidence"})
                continue
        key = str(path).casefold()
        item = dict(item)
        item["absolute_path"] = str(path)
        item["relative_path"] = rel(path)
        item["bytes"] = int(summary["dir_sizes"].get(str(path), item.get("bytes", 0))) if item["entry_type"] == "directory" else int(item.get("bytes", 0))
        selected[key] = item
    ordered = sorted(selected.values(), key=lambda row: len(str(row["absolute_path"])))
    normalized: list[dict[str, object]] = []
    for item in ordered:
        path = str(item["absolute_path"]).casefold().rstrip("\\/")
        if any(path.startswith(str(parent["absolute_path"]).casefold().rstrip("\\/") + os.sep) for parent in normalized):
            continue
        nested_reparse = [p for p in summary["reparse_points"] if str(p).casefold().startswith(path + os.sep)]
        if nested_reparse:
            raise RuntimeError(f"candidate contains reparse point: {item['absolute_path']}")
        if int(item["bytes"]) <= 0:
            continue
        normalized.append(item)
    return normalized, retained_time


def checkpoint_hash_manifest() -> dict[str, object]:
    requested = ["U", "p", "phi", "Uf", "meshPhi", "motionScale", "polyMesh/points", "uniform/time"]
    records: list[dict[str, object]] = []
    for label, base in (("Ur5p2_common_coarse_130", CASES / "single_dof_free_viv_Ur5p2_v8_dt0025_from130" / "130"), ("Ur5p2_common_refined_130", CASES / "single_dof_free_viv_Ur5p2_v8_dt00125_from130" / "130"), ("Ur5p2_coarse_final_150", CASES / "single_dof_free_viv_Ur5p2_v8_dt0025_from130" / "150"), ("Ur5p2_refined_final_150", CASES / "single_dof_free_viv_Ur5p2_v8_dt00125_from130" / "150")):
        for name in requested:
            records.extend(file_hash_records([(label, base / Path(name))]))
    for relative in ("results/04_sdof_corrected_campaign/Ur5p2_v6_retry_to130/sdof_checkpoint.json", "results/04_sdof_corrected_campaign/dt_convergence_v8/Ur5p2_dt0025_from130/sdof_checkpoint.json", "results/04_sdof_corrected_campaign/dt_convergence_v8/Ur5p2_dt00125_from130/sdof_checkpoint.json"):
        records.extend(file_hash_records([("structural_checkpoint", ROOT / Path(relative))]))
    key_case_records: list[dict[str, object]] = []
    if CASES.is_dir():
        for case in sorted(CASES.iterdir()):
            if not case.is_dir() or not KEY_CASE.search(case.name):
                continue
            times = [p for p in case.iterdir() if p.is_dir() and NUMERIC_TIME.fullmatch(p.name)]
            if not times:
                continue
            final = max(times, key=lambda p: float(p.name))
            key_case_records.append({"label": f"key_case_final_{case.name}", "path": final})
    for item in key_case_records:
        base = Path(item["path"])
        for path in sorted(base.rglob("*")):
            if path.is_file() and inside(path):
                records.extend(file_hash_records([(str(item["label"]), path)]))
    return {"schema_version": "stage3_v8_checkpoint_hash_manifest", "generated_utc": now(), "project_root": str(ROOT), "common_time_s": 130.0, "common_state": {"y": 0.4324133716360857, "v": 0.15568921471030148, "a": -0.6076706275402103, "time_s": 130.0, "step": 52000, "previous_force_y_N": 215.3214405}, "field_hashes": records}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    CLEANUP.mkdir(parents=True, exist_ok=True)
    summary = walk()
    candidates, retained_time = build_candidates(summary)
    drive = shutil.disk_usage(ROOT.drive + os.sep)
    drive_snapshot = {"drive": ROOT.drive, "total_bytes": int(drive.total), "free_bytes": int(drive.free), "used_bytes": int(drive.total - drive.free)}
    candidate_bytes = sum(int(row["bytes"]) for row in candidates)
    categories = []
    for category in sorted({str(row["category"]) for row in candidates}):
        rows = [row for row in candidates if row["category"] == category]
        categories.append({"category": category, "count": len(rows), "bytes": sum(int(row["bytes"]) for row in rows)})
    inventory = {"schema_version": "project_inventory_v8", "phase": "pre_cleanup", "generated_utc": now(), "project_root": str(ROOT), "logical_size_bytes": int(summary["logical_bytes"]), "logical_size_GB": round(int(summary["logical_bytes"]) / 1_000_000_000, 3), "file_count": int(summary["file_count"]), "directory_count": int(summary["directory_count"]), "drive": drive_snapshot, "reparse_points": summary["reparse_points"], "top_50_directories": summary["top_directories"], "top_100_files": summary["top_files"], "extension_bytes": summary["extension_bytes"], "candidate_count": len(candidates), "candidate_bytes": candidate_bytes, "candidate_categories": categories}
    write_json(CLEANUP / "pre_cleanup_inventory_v8.json", inventory)
    hash_manifest = checkpoint_hash_manifest()
    write_json(CLEANUP / "stage3_v8_checkpoint_hash_manifest.json", hash_manifest)
    fields = ["absolute_path", "relative_path", "entry_type", "bytes", "reason", "regenerable_from", "stage_workload", "category", "reparse_checked"]
    for row in candidates:
        row["reparse_checked"] = True
    write_csv(CLEANUP / "delete_manifest_v8.csv", candidates, fields)
    retain_rows = []
    for relative in ("src", "tests", "scripts", "docs", ".git", "results/04_continuous_fsi", "results/04_sdof_corrected_campaign", "cases/openfoam"):
        path = ROOT / Path(relative)
        if path.exists():
            retain_rows.append({"relative_path": relative, "absolute_path": str(path), "entry_type": "protected_tree", "bytes": int(summary["dir_sizes"].get(str(path.resolve()), 0)), "reason": "source, tests, docs, Git or evidence tree; only exact manifest targets may be deleted", "required_for": "stage4 development and reproducibility"})
    for relative in ("docs/04_stage3_final_acceptance_report_v8.md", "docs/04_stage3_acceptance_matrix_v8.md", "docs/04_stage4_entry_decision_v8.md", "results/04_continuous_fsi/stage3_final_metrics_v8.json", "results/04_continuous_fsi/stage3_v8_test_results.json", "results/04_continuous_fsi/stage3_v8_matlab_test_results.json", "results/04_sdof_corrected_campaign/asymptotic_v8/Ur8_asymptotic_v8.json", "results/04_sdof_corrected_campaign/dt_convergence_v8/long_window_dt_convergence_v8.json", "results/04_sdof_corrected_campaign/dt_convergence_v8/common_checkpoint_manifest_v8.json"):
        path = ROOT / Path(relative)
        if path.is_file():
            retain_rows.append({"relative_path": relative, "absolute_path": str(path), "entry_type": "critical_evidence", "bytes": path.stat().st_size, "reason": "required v8 final machine-readable evidence", "required_for": "acceptance audit"})
    for case in sorted(CASES.iterdir()) if CASES.is_dir() else []:
        if not case.is_dir():
            continue
        for name in ("0", "constant", "system"):
            path = case / name
            if path.is_dir():
                retain_rows.append({"relative_path": rel(path), "absolute_path": str(path), "entry_type": "case_base", "bytes": int(summary["dir_sizes"].get(str(path.resolve()), 0)), "reason": "OpenFOAM base case configuration", "required_for": "future rerun/restart"})
    retain_rows.extend(retained_time)
    write_csv(CLEANUP / "retain_manifest_v8.csv", retain_rows, ["relative_path", "absolute_path", "entry_type", "bytes", "reason", "required_for"])
    categories_md = "\n".join(f"| {item['category']} | {item['count']} | {item['bytes']/1_000_000_000:.3f} GB |" for item in sorted(categories, key=lambda row: row["bytes"], reverse=True))
    plan = f"""# Project cleanup plan v8

No deletion is performed by this audit script. The exact PowerShell executor must read `results/cleanup/delete_manifest_v8.csv`.

- Root: `{ROOT}`
- Pre-clean logical size: {summary['logical_bytes']/1_000_000_000:.3f} GB; files: {summary['file_count']}; directories: {summary['directory_count']}.
- Exact non-overlapping candidates: {len(candidates)}; estimated logical release: {candidate_bytes/1_000_000_000:.3f} GB.
- Reparse points discovered: {len(summary['reparse_points'])}; none are followed. Any candidate containing one aborts execution.
- Numeric OpenFOAM time policy: retain `0`, `constant`, `system`, latest numeric time per case, and explicit v8/Ur checkpoint times; delete only intermediate exact directories.

| category | count | bytes |
|---|---:|---:|
{categories_md}
"""
    (ROOT / "docs" / "cleanup_plan_v8.md").write_text(plan, encoding="utf-8")
    dry = f"""# Cleanup dry-run v8

Status: **READY FOR REVIEWED EXECUTION**; no files were deleted.

- Candidate count: {len(candidates)}
- Estimated logical release: {candidate_bytes/1_000_000_000:.3f} GB
- Delete manifest: `results/cleanup/delete_manifest_v8.csv`
- Retain manifest: `results/cleanup/retain_manifest_v8.csv`
- Checkpoint hashes: `results/cleanup/stage3_v8_checkpoint_hash_manifest.json`

All targets are exact paths strictly below the project root. Source, tests, docs, Git metadata, final v8 evidence and case base configuration are excluded.
"""
    (ROOT / "docs" / "cleanup_dry_run_v8.md").write_text(dry, encoding="utf-8")
    print(json.dumps({"mode": "dry_run", "project_root": str(ROOT), "pre_logical_GB": round(summary["logical_bytes"] / 1_000_000_000, 3), "pre_files": summary["file_count"], "pre_directories": summary["directory_count"], "candidate_count": len(candidates), "candidate_GB": round(candidate_bytes / 1_000_000_000, 3), "reparse_points": len(summary["reparse_points"]), "hash_records": len(hash_manifest["field_hashes"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
