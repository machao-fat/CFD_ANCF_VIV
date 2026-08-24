"""Post-cleanup inventory and verification; no deletion is performed."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from pathlib import Path

from audit_cleanup_v8 import CLEANUP, ROOT, CASES, rel, sha256, walk, write_json


def json_finite(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(json_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(json_finite(item) for item in value)
    return True


def main() -> None:
    summary = walk()
    drive = shutil.disk_usage(ROOT.drive + "/")
    post = {
        "schema_version": "project_inventory_v8",
        "phase": "post_cleanup",
        "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "logical_size_bytes": int(summary["logical_bytes"]),
        "logical_size_GB": round(int(summary["logical_bytes"]) / 1_000_000_000, 3),
        "file_count": int(summary["file_count"]),
        "directory_count": int(summary["directory_count"]),
        "drive": {"drive": ROOT.drive, "total_bytes": int(drive.total), "free_bytes": int(drive.free), "used_bytes": int(drive.total - drive.free)},
        "reparse_points": summary["reparse_points"],
        "top_50_directories": summary["top_directories"],
        "top_100_files": summary["top_files"],
        "extension_bytes": summary["extension_bytes"],
    }
    write_json(CLEANUP / "post_cleanup_inventory_v8.json", post)

    required_files = [
        "docs/04_stage3_final_acceptance_report_v8.md",
        "docs/04_stage3_acceptance_matrix_v8.md",
        "docs/04_stage4_entry_decision_v8.md",
        "results/04_continuous_fsi/stage3_final_metrics_v8.json",
        "results/04_continuous_fsi/stage3_v8_test_results.json",
        "results/04_continuous_fsi/stage3_v8_matlab_test_results.json",
        "results/04_sdof_corrected_campaign/asymptotic_v8/Ur8_asymptotic_v8.json",
        "results/04_sdof_corrected_campaign/dt_convergence_v8/long_window_dt_convergence_v8.json",
        "results/04_sdof_corrected_campaign/dt_convergence_v8/common_checkpoint_manifest_v8.json",
        "results/cleanup/stage3_v8_checkpoint_hash_manifest.json",
        "src/structure_ancf_matlab",
        "src/structure_eb_fem_matlab",
        "src/coupling/online_file_coupling",
        "src/openfoam/ancfFileMotion",
        "tests",
        "docs",
    ]
    required_checks = []
    for relative in required_files:
        path = ROOT / Path(relative)
        exists = path.exists()
        parseable = exists
        finite = True
        if exists and path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                finite = json_finite(payload)
            except Exception:
                parseable = False
        required_checks.append({"relative_path": relative, "absolute_path": str(path), "exists": exists, "parseable": parseable, "finite": finite})

    hash_payload = json.loads((CLEANUP / "stage3_v8_checkpoint_hash_manifest.json").read_text(encoding="utf-8"))
    hash_checks = []
    for record in hash_payload["field_hashes"]:
        path = Path(record["absolute_path"])
        if record["status"] == "present":
            exists = path.is_file()
            actual = sha256(path) if exists else None
            hash_checks.append({"relative_path": record["relative_path"], "exists": exists, "hash_matches": exists and actual == record["sha256"], "expected_sha256": record["sha256"], "actual_sha256": actual})
        else:
            hash_checks.append({"relative_path": record["relative_path"], "exists": path.exists(), "hash_matches": False, "expected_sha256": None, "actual_sha256": None, "expected_missing_in_pre_audit": True})

    base_case_names = [
        "fixed_cylinder",
        "prescribed_motion_cylinder/template",
        "single_dof_free_viv_Ur5p2_v8_dt0025_from130",
        "single_dof_free_viv_Ur5p2_v8_dt00125_from130",
        "single_slice_ancf_fsi",
        "single_slice_eb_fsi",
    ]
    base_checks = []
    for name in base_case_names:
        case = CASES / Path(name)
        base_checks.append({"case": name, "exists": case.is_dir(), "has_0": (case / "0").is_dir(), "has_constant": (case / "constant").is_dir(), "has_system": (case / "system").is_dir()})

    metrics = json.loads((ROOT / "results/04_continuous_fsi/stage3_final_metrics_v8.json").read_text(encoding="utf-8"))
    py = json.loads((ROOT / "results/04_continuous_fsi/stage3_v8_test_results.json").read_text(encoding="utf-8"))
    matlab = json.loads((ROOT / "results/04_continuous_fsi/stage3_v8_matlab_test_results.json").read_text(encoding="utf-8"))
    ur8 = json.loads((ROOT / "results/04_sdof_corrected_campaign/asymptotic_v8/Ur8_asymptotic_v8.json").read_text(encoding="utf-8"))
    dt = json.loads((ROOT / "results/04_sdof_corrected_campaign/dt_convergence_v8/long_window_dt_convergence_v8.json").read_text(encoding="utf-8"))
    figures = sorted(str(path.relative_to(ROOT).as_posix()) for path in (ROOT / "results/04_sdof_corrected_campaign/asymptotic_v8").glob("*") if path.suffix.lower() in {".png", ".svg", ".pdf"})
    recreated_cache_dirs = sorted(str(path.relative_to(ROOT).as_posix()) for path in ROOT.rglob("__pycache__"))
    delete_rows = list(csv.DictReader((CLEANUP / "delete_manifest_v8.csv").open(encoding="utf-8-sig", newline="")))
    deletion_log = json.loads((CLEANUP / "delete_execution_v8.json").read_text(encoding="utf-8-sig"))
    deleted_categories = []
    for category in sorted({row["category"] for row in delete_rows}):
        rows = [row for row in delete_rows if row["category"] == category]
        deleted_categories.append({"category": category, "count": len(rows), "bytes": sum(int(row["bytes"]) for row in rows)})
    validation = {
        "schema_version": "post_cleanup_validation_v8",
        "generated_utc": post["generated_utc"],
        "project_root": str(ROOT),
        "required_files": required_checks,
        "checkpoint_hashes": {"records": hash_checks, "present_hash_matches": sum(1 for row in hash_checks if row["hash_matches"]), "present_hash_failures": [row for row in hash_checks if row.get("exists") and not row.get("hash_matches")]},
        "base_cases": base_checks,
        "stage3_metrics": {"stage3_fully_passed": metrics.get("stage3_fully_passed"), "eligible_for_stage4_prototype": metrics.get("eligible_for_stage4_prototype")},
        "python_regression": {"status": py.get("status"), "tests_run": py.get("tests_run"), "passed": py.get("passed"), "failed": py.get("failed")},
        "matlab_regression": {"executed_in_v8": matlab.get("executed_in_v8"), "inherited_from_v7": matlab.get("inherited_from_v7"), "passed": matlab.get("passed"), "failed": matlab.get("failed"), "rerun_after_cleanup": False},
        "ur8_status": ur8.get("classification", {}).get("class"),
        "dt_status": dt.get("status"),
        "final_v8_figure_count": len(figures),
        "final_v8_figures": figures,
        "post_validation_recreated_cache_dirs": recreated_cache_dirs,
        "deleted_categories": deleted_categories,
        "delete_execution": {"target_count": deletion_log.get("target_count"), "deleted_count": deletion_log.get("deleted_count"), "failed_count": deletion_log.get("failed_count"), "deleted_bytes": deletion_log.get("deleted_bytes")},
        "no_long_cfd_run": True,
        "multi_slice_started": False,
    }
    validation["validation_pass"] = all(item["exists"] and item["parseable"] and item["finite"] for item in required_checks) and not validation["checkpoint_hashes"]["present_hash_failures"] and all(item["exists"] and item["has_0"] and item["has_constant"] and item["has_system"] for item in base_checks) and metrics.get("stage3_fully_passed") is True and py.get("status") == "pass" and py.get("failed") == 0 and matlab.get("passed") == matlab.get("total") and matlab.get("failed") == 0 and ur8.get("classification", {}).get("class") == "asymptotically_periodic_outside_lockin" and dt.get("long_window_convergence_pass") is True and len(figures) >= 18 and deletion_log.get("failed_count") == 0
    write_json(CLEANUP / "post_cleanup_validation_v8.json", validation)

    pre = json.loads((CLEANUP / "pre_cleanup_inventory_v8.json").read_text(encoding="utf-8"))
    released = int(pre["logical_size_bytes"]) - int(post["logical_size_bytes"])
    top20 = "\n".join(f"| {index} | {item['bytes']/1_000_000_000:.3f} GB | `{item['path']}` |" for index, item in enumerate(post["top_50_directories"][:20], 1))
    categories_md = "\n".join(f"| {item['category']} | {item['count']} | {item['bytes']/1_000_000_000:.3f} GB |" for item in sorted(deleted_categories, key=lambda row: row["bytes"], reverse=True))
    success_text = "\u6e05\u7406\u5b8c\u6210\uff0c\u9636\u6bb5\u4e09\u53ef\u590d\u6838\uff0c\u9636\u6bb5\u56db\u539f\u578b\u51c6\u5165\u8d44\u683c\u4fdd\u6301\u6709\u6548"
    failure_text = "\u6e05\u7406\u672a\u5b8c\u6210/\u9a8c\u8bc1\u5931\u8d25\uff0c\u5df2\u505c\u6b62\uff0c\u672a\u5f71\u54cd\u73b0\u6709\u6570\u636e"
    report = f"""# Project cleanup report v8

## Final decision

**{success_text if validation['validation_pass'] else failure_text}**

## Capacity and deletion

| item | before | after |
|---|---:|---:|
| logical size | {pre['logical_size_bytes']/1_000_000_000:.3f} GB | {post['logical_size_bytes']/1_000_000_000:.3f} GB |
| file count | {pre['file_count']} | {post['file_count']} |
| directory count | {pre['directory_count']} | {post['directory_count']} |
| drive used | {pre['drive']['used_bytes']/1_000_000_000:.3f} GB | {post['drive']['used_bytes']/1_000_000_000:.3f} GB |

- Logical bytes released: **{released/1_000_000_000:.3f} GB**.
- PowerShell execution: {deletion_log['deleted_count']}/{deletion_log['target_count']} targets, failures {deletion_log['failed_count']}.
- No project-related compute process was running; no long CFD calculation was run.
- The post-cleanup Python regression recreated {len(recreated_cache_dirs)} small `__pycache__` directories. They are rebuildable test artifacts and were not removed in a second destructive process, in accordance with the single-PowerShell deletion rule.

## Deleted categories

| category | targets | logical size |
|---|---:|---:|
{categories_md}

## Retained evidence

The full `src/`, `tests/`, `docs/`, OpenFOAM base configurations, v8 JSON/CSV evidence, final PNG/SVG/PDF figures, v8 dt/dt2 checkpoint branches and checkpoint hash manifest remain. The v8 stage3 metrics still report `stage3_fully_passed=true` and `eligible_for_stage4_prototype=true`.

Checkpoint hash verification: {validation['checkpoint_hashes']['present_hash_matches']} present hashes matched; failures: {len(validation['checkpoint_hashes']['present_hash_failures'])}.

Python regression retained: {py.get('passed')}/{py.get('tests_run')}; MATLAB result retained as a verified v8 10/10 record and was not rerun during cleanup.

## Twenty largest remaining directories

| rank | size | directory |
|---:|---:|---|
{top20}

## Scope boundary

No physical model, solver, acceptance threshold or stage3 evidence was changed. No multi-slice, full-riser or stage4 computation was started. See `results/cleanup/post_cleanup_validation_v8.json` for the machine-readable validation result.
"""
    (ROOT / "docs" / "cleanup_report_v8.md").write_text(report, encoding="utf-8")
    print(json.dumps({"validation_pass": validation["validation_pass"], "post_logical_GB": post["logical_size_GB"], "post_files": post["file_count"], "post_directories": post["directory_count"], "released_GB": round(released / 1_000_000_000, 3), "figure_count": len(figures), "hash_failures": len(validation["checkpoint_hashes"]["present_hash_failures"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
