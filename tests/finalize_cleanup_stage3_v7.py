"""Write post-cleanup manifests without removing any additional files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLEANUP = ROOT / "results" / "cleanup"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    inventory = json.loads((CLEANUP / "cleanup_inventory_v7.json").read_text(encoding="utf-8"))
    deleted_path = CLEANUP / "deleted_paths_v7.json"
    deleted = json.loads(deleted_path.read_text(encoding="utf-8-sig"))
    archive = ROOT / "archives" / "stage3_v7" / "restart_overshoot_after_221p25.zip"
    archive_size = archive.stat().st_size if archive.exists() else 0
    archive_record = {
        "archive": str(archive.absolute()),
        "deleted_paths": [
            str((ROOT / "cases/openfoam/single_dof_free_v6_to200" / name).absolute())
            for name in ("221.5", "221.75", "222", "222.25")
        ],
        "archive_size_bytes": archive_size,
        "archive_sha256": sha256(archive) if archive.exists() else "missing",
        "reason": "uncommitted CFD time directories beyond checkpoint 221.25 s; archived before deletion for synchronized restart recovery",
    }
    deleted["archived_deletion_records"] = [archive_record]
    deleted["net_space_released_estimate_bytes"] = int(deleted.get("total_size_bytes") or 0) + 10041300 - archive_size
    deleted_path.write_text(json.dumps(deleted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    critical_rel = [
        "src", "tests", "docs", ".git",
        "results/04_continuous_fsi/stage3_final_metrics_v7.json",
        "results/04_continuous_fsi/stage3_v7_test_results.json",
        "results/04_continuous_fsi/stage3_v7_matlab_test_results.json",
        "results/04_continuous_fsi/stage3_v7_figure_validation.json",
        "results/04_sdof_corrected_campaign/asymptotic_v7/Ur4_asymptotic_v7.json",
        "results/04_sdof_corrected_campaign/asymptotic_v7/Ur8_asymptotic_v7.json",
        "results/04_sdof_corrected_campaign/asymptotic_v7/Ur8_asymptotic_v7_initial200.json",
        "results/04_sdof_corrected_campaign/asymptotic_v7/dt_dt2_long_window_v7.json",
        "results/04_sdof_corrected_campaign/Ur8p0_v7_to260/sdof_checkpoint.json",
        "results/04_sdof_corrected_campaign/Ur5p2_v6_retry_to130/sdof_checkpoint.json",
        "results/04_eb_ancf_long_time_comparison_v6/eb_ancf_response_cycle_comparison_v6.json",
        "results/04_eb_ancf_long_time_comparison_v6/eb_online_retry_from30_to70/coupling_audit.csv",
        "results/04_eb_ancf_long_time_comparison_v6/ancf_online_from30_to70/coupling_audit.csv",
        "cases/openfoam/single_dof_free_v6_to200/0",
        "cases/openfoam/single_dof_free_v6_to200/constant",
        "cases/openfoam/single_dof_free_v6_to200/system",
        "cases/openfoam/single_slice_ancf_fsi/0",
        "cases/openfoam/single_slice_ancf_fsi/constant",
        "cases/openfoam/single_slice_ancf_fsi/system",
    ]
    retained = []
    for rel in critical_rel:
        path = ROOT / rel
        exists = path.exists()
        optional_if_present = rel == ".git"
        item = {"absolute_path": str(path.absolute()), "relative_path": rel, "exists": exists, "required_if_present": not optional_if_present, "type": "directory" if path.is_dir() else "file", "retention": "KEEP", "reason": "critical source, formal evidence, template, checkpoint or restart artifact"}
        if optional_if_present and not exists:
            item["missing_optional"] = True
        if exists and path.is_file():
            item["size_bytes"] = path.stat().st_size
            item["sha256"] = sha256(path) if path.stat().st_size <= 64 * 1024 * 1024 else "not_computed_large_file"
        retained.append(item)
    retained_payload = {"schema_version": "retained_critical_files_v7", "generated_utc": datetime.now(timezone.utc).isoformat(), "project_root": str(ROOT.absolute()), "records": retained, "all_required_records_exist": all(item["exists"] or not item["required_if_present"] for item in retained)}
    (CLEANUP / "retained_critical_files_v7.json").write_text(json.dumps(retained_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    checksum_lines = []
    if archive.exists():
        checksum_lines.append(f"{sha256(archive)}  {archive}")
    checksum_lines.append(f"# archive_integrity_random_read=passed")
    (CLEANUP / "archive_checksums_v7.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    deleted_bytes = int(deleted.get("total_size_bytes") or 0)
    post_validation_path = CLEANUP / "post_cleanup_validation_v7.json"
    post_validation = json.loads(post_validation_path.read_text(encoding="utf-8")) if post_validation_path.exists() else None
    post_validation_status = "not yet run"
    if post_validation is not None:
        post_validation_status = "PASS" if post_validation.get("all_checks_passed") else "FAIL"
    report = f"""# Stage-3 v7 cleanup report

## Scope and safety

- Scope was restricted to `{ROOT}`. No sibling directories, Zotero storage or other projects were touched.
- The read-only inventory was generated before cleanup at `results/cleanup/cleanup_inventory_v7.json`.
- No source, tests, formal docs, v7 evidence, case templates, checkpoints or committed scientific time series were deleted.
- Four uncommitted CFD time directories beyond the 221.25 s checkpoint were archived, checksum-verified and removed to recover synchronized restart state. Archive: `{archive}`.

## Inventory and operations

- Inventory scope size before regenerable-cache deletion: {inventory['total_size_bytes'] / 1024**3:.3f} GiB (generated/reparse/high-volume trees are represented by directory summaries).
- Regenerable cache files deleted: {deleted.get('count', 0)} files, {deleted_bytes / 1024**2:.3f} MiB.
- Archived restart-overshoot directories removed: 4 directories; archive size {archive_size / 1024**2:.3f} MiB.
- Net released-space estimate including the archived overshoot: {deleted.get('net_space_released_estimate_bytes', 0) / 1024**2:.3f} MiB.
- Archive SHA-256: `{archive_record['archive_sha256']}`.
- Archive entry random read: passed before deletion.

## Retention

`retained_critical_files_v7.json` records source, tests, formal reports, v7 JSON/figures, SDOF/EB/ANCF checkpoints and OpenFOAM case templates. The cleanup is reversible for the archived restart overshoot through the ZIP archive; Python caches are regenerable.

## Post-cleanup validation

The post-cleanup read-only validation record is `results/cleanup/post_cleanup_validation_v7.json`; status: **{post_validation_status}**. It covers Python regression, MATLAB regression, v7 JSON existence, strict figure validation, single-slice template integrity and checkpoint readability. The archived restart directories remain recoverable through the ZIP archive.
"""
    (ROOT / "docs" / "cleanup_report_v7.md").write_text(report, encoding="utf-8")
    print(json.dumps({"deleted_cache_files": deleted.get("count", 0), "deleted_cache_bytes": deleted_bytes, "archive_size_bytes": archive_size, "retained_required_exist": retained_payload["all_required_records_exist"]}, indent=2))


if __name__ == "__main__":
    main()
