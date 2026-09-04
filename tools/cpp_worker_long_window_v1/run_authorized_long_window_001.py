"""Run the one explicitly authorized 800-step C++/OpenFOAM continuation.

The coordinator and numerical path are inherited from the accepted bounded
confirm.  This wrapper supplies the sole larger authorization, continuation
source, and post-success evidence-compaction policy.  It never retries and
never extends past global step 1439.
"""

from __future__ import annotations

import math
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm


STAGE_ID = "stage4f_d_cpp_worker_long_window_v1"
RUN_ID = "cpp_worker_long_window_001"
CASE_ID = "cpp_worker_long_window_case_001"
SOURCE_STEP = 639
SOURCE_TIME_S = 2.3075
SOURCE_TICK = 2_307_500_000
AUTHORIZED_STEPS = 800
DT_S = 0.00125
KEEP_FULL_STEPS = 40
TARGET_STEP = SOURCE_STEP + AUTHORIZED_STEPS
TARGET_TIME_S = SOURCE_TIME_S + AUTHORIZED_STEPS * DT_S
TARGET_TICK = SOURCE_TICK + AUTHORIZED_STEPS * 1_250_000
KEEP_FROM_STEP = TARGET_STEP - KEEP_FULL_STEPS + 1
KEEP_FROM_TIME_S = SOURCE_TIME_S + (KEEP_FROM_STEP - SOURCE_STEP) * DT_S

SOURCE = PROJECT / "runtime/cpp_worker_long_window_v1/source_derivation_001/continuation_source_step00000639_v1.json"
SOURCE_SHA256 = "e88feafb3efd4b9428ac04cd3d207aa0d5288a9a35c93e5a6bc9fad034c4612a"
TEMPLATE_ROOT = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_017/cases"
RUNTIME = PROJECT / "runtime/cpp_worker_long_window_v1/long_window_001"
RESULTS = PROJECT / "results/209_cpp_worker_long_window_v1"
DOCS = PROJECT / "docs/209_cpp_worker_long_window_v1"


def _is_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.stat(), "st_file_attributes", 0) & 0x400)


def _assert_owned(path: Path, root: Path) -> None:
    if _is_reparse(path):
        raise RuntimeError(f"retention refuses reparse point: {path}")
    if path.resolve().parent != root.resolve():
        raise RuntimeError(f"retention target is outside the fresh case root: {path}")


def _prepare_fresh_case_destination(destination: Path, *, slice_id: int) -> None:
    """Prepare and verify the restart clock before any external launch."""
    expected = RUNTIME / "cases" / f"slice_{slice_id:04d}"
    if destination.resolve() != expected.resolve():
        raise RuntimeError("unexpected fresh case destination")
    stale_bridge = destination / "coupling"
    if not stale_bridge.is_dir() or _is_reparse(stale_bridge):
        raise RuntimeError("continuation template coupling directory is invalid")
    # ``destination`` was just created by copytree inside the fresh runtime;
    # this cannot reach the protected Stage204 source template.
    shutil.rmtree(stale_bridge)
    _rewrite_restart_clock(destination, slice_id=slice_id)


def _rewrite_restart_clock(destination: Path, *, slice_id: int) -> None:
    """Bind a copied final case to the continuation source time exactly."""
    source_time_name = format(SOURCE_TIME_S, ".12g")
    source_time_dir = destination / source_time_name
    if not source_time_dir.is_dir() or _is_reparse(source_time_dir):
        raise RuntimeError("continuation source-time field directory is missing")
    control = destination / "system" / "controlDict"
    text = control.read_text(encoding="utf-8")
    text, start_from_count = re.subn(
        r"^startFrom\s+[^;]+;", "startFrom       startTime;", text, count=1, flags=re.MULTILINE)
    text, start_time_count = re.subn(
        r"^startTime\s+[^;]+;", f"startTime       {source_time_name};", text, count=1, flags=re.MULTILINE)
    if start_from_count != 1 or start_time_count != 1:
        raise RuntimeError("continuation controlDict has no unique restart clock entries")
    control.write_text(text, encoding="utf-8")
    verified = control.read_text(encoding="utf-8")
    if not re.search(rf"^startFrom\s+startTime;\s*$", verified, flags=re.MULTILINE) or not re.search(
            rf"^startTime\s+{re.escape(source_time_name)};\s*$", verified, flags=re.MULTILINE):
        raise RuntimeError("continuation restart clock write verification failed")
    motion_dict = destination / "constant" / "dynamicMeshDict"
    motion_text = motion_dict.read_text(encoding="utf-8")
    motion_text, motion_start_count = re.subn(
        r"(^\s*startTime\s+)[^;]+;", rf"\g<1>{source_time_name};", motion_text,
        count=1, flags=re.MULTILINE)
    if motion_start_count != 1:
        raise RuntimeError("ancfFileMotion restart startTime entry is missing or ambiguous")
    motion_dict.write_text(motion_text, encoding="utf-8")
    verified_motion = motion_dict.read_text(encoding="utf-8")
    if not re.search(rf"^\s*startTime\s+{re.escape(source_time_name)};\s*$", verified_motion, flags=re.MULTILINE):
        raise RuntimeError("ancfFileMotion restart clock write verification failed")
    config_path = destination / "multi_slice_case_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["case_id"] = f"{CASE_ID}_slice_{slice_id:04d}"
    config["run_id"] = RUN_ID
    confirm._write(config_path, config)
    confirm._write(destination / "continuation_restart_clock_audit.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "slice_id": slice_id,
        "source_time_s": SOURCE_TIME_S, "source_time_directory": source_time_name,
        "control_dict_start_from": "startTime", "control_dict_start_time_s": SOURCE_TIME_S,
        "ancf_file_motion_start_time_s": SOURCE_TIME_S,
        "verified_before_external_launch": True,
    })


def _numeric_time(name: str) -> float | None:
    try:
        value = float(name)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0.0 else None


def _file_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(root.rglob("*")):
        if item.is_dir():
            if _is_reparse(item):
                raise RuntimeError(f"retention refuses nested reparse point: {item}")
            continue
        if not item.is_file() or _is_reparse(item):
            raise RuntimeError(f"retention refuses non-regular artifact: {item}")
        stat = item.stat()
        rows.append({"relative_path": str(item.relative_to(root)), "size_bytes": stat.st_size,
                     "mtime_ns": stat.st_mtime_ns, "sha256": confirm._sha256(item)})
    return rows


def _post_success_retention(*, runtime: Path, results: Path,
                            checkpoint_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep source/final and the final 40 full fields after hashing all others."""
    if runtime.resolve() != RUNTIME.resolve() or len(checkpoint_rows) != AUTHORIZED_STEPS:
        raise RuntimeError("retention scope is not the exact authorized window")
    manifest_rows: list[dict[str, Any]] = []
    delete_targets: list[Path] = []
    cases_root = runtime / "cases"
    for slice_id in range(3):
        case_root = cases_root / f"slice_{slice_id:04d}"
        if not case_root.is_dir() or _is_reparse(case_root):
            raise RuntimeError(f"fresh case root is invalid: {case_root}")
        for candidate in sorted(case_root.iterdir()):
            value = _numeric_time(candidate.name)
            if value is None or candidate.name == "0":
                continue
            # Source restart state and final 40 steps remain restartable.
            preserve = (abs(value - SOURCE_TIME_S) <= 1.0e-12 or value >= KEEP_FROM_TIME_S - 1.0e-12)
            if preserve:
                continue
            _assert_owned(candidate, case_root)
            manifest_rows.append({"slice_id": slice_id, "time_s": value,
                                  "path": str(candidate), "files": _file_manifest(candidate)})
            delete_targets.append(candidate)
    manifest = {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "policy": {"source_time_s_preserved": SOURCE_TIME_S,
                   "final_full_steps_preserved": KEEP_FULL_STEPS,
                   "keep_from_step": KEEP_FROM_STEP, "keep_from_time_s": KEEP_FROM_TIME_S,
                   "all_step_telemetry_and_checkpoint_manifests_preserved": True},
        "compaction_candidates": manifest_rows,
        "source_read_only": str(SOURCE),
    }
    # The manifest is durable before any Stage209 artifact is deleted.
    confirm._write(results / "retention_predelete_manifest.json", manifest)
    for target in delete_targets:
        _assert_owned(target, target.parent)
        shutil.rmtree(target)
        if target.exists():
            raise RuntimeError(f"retention target still exists after deletion: {target}")
    audit = {"status": "compacted", "deleted_full_artifact_directories": len(delete_targets),
             "deleted_file_count": sum(len(row["files"]) for row in manifest_rows),
             "preserved_full_restart_steps": KEEP_FULL_STEPS,
             "source_checkpoint_preserved": str(SOURCE),
             "checkpoint_rows_preserved": len(checkpoint_rows),
             "telemetry_preserved": AUTHORIZED_STEPS}
    confirm._write(results / "retention_audit.json", audit)
    return audit


confirm.STAGE_ID = STAGE_ID
confirm.RUN_ID = RUN_ID
confirm.CASE_ID = CASE_ID
confirm.RUNTIME = RUNTIME
confirm.RESULTS = RESULTS
confirm.DOCS = DOCS
confirm.SOURCE = SOURCE
confirm.SOURCE_SHA256 = SOURCE_SHA256
confirm.TEMPLATE_ROOT = TEMPLATE_ROOT
confirm.SOURCE_GLOBAL_STEP = SOURCE_STEP
confirm.SOURCE_TIME_S = SOURCE_TIME_S
confirm.SOURCE_TICK = SOURCE_TICK
confirm.AUTHORIZED_STEPS = AUTHORIZED_STEPS
confirm.TARGET_FINAL_STEP = TARGET_STEP
confirm.TARGET_FINAL_TIME_S = TARGET_TIME_S
confirm.TARGET_FINAL_TICK = TARGET_TICK
confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_LONG_WINDOW_V1_GATE"
confirm.GATE_FILENAME = "stage4f_d_cpp_worker_long_window_v1_gate.json"
confirm._prepare_fresh_case_destination = _prepare_fresh_case_destination
confirm._post_success_retention = _post_success_retention


if __name__ == "__main__":
    raise SystemExit(confirm.main())
