"""Fresh-case preparation for a 6.0 s portable restart.

This operates only on a case copy that already lives inside the caller's new
runtime. It deliberately never mutates the Stage214 source template.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


SOURCE_TIME_S = 6.0


def _is_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def prepare_fresh_case(*, destination: Path, expected_destination: Path, slice_id: int,
                       run_id: str, case_id: str, stage_id: str) -> None:
    """Discard inherited bridge artifacts and bind one fresh copy to 6.0 s."""
    if destination.resolve() != expected_destination.resolve():
        raise RuntimeError("unexpected fresh case destination")
    if not destination.is_dir() or _is_reparse(destination):
        raise RuntimeError("fresh case destination is invalid")
    bridge = destination / "coupling"
    if not bridge.is_dir() or _is_reparse(bridge):
        raise RuntimeError("source template coupling directory is invalid")
    # The copied bridge belongs solely to the old Stage214 runtime. Delete it
    # before the coordinator creates a new, empty consumed namespace.
    shutil.rmtree(bridge)
    source_time = format(SOURCE_TIME_S, ".12g")
    for candidate in list(destination.iterdir()):
        try:
            numeric_time = float(candidate.name)
        except ValueError:
            continue
        if candidate.name == "0" or abs(numeric_time - SOURCE_TIME_S) <= 1e-12:
            continue
        if _is_reparse(candidate):
            raise RuntimeError("restart template contains a reparse point")
        if candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()
    if not (destination / source_time).is_dir():
        raise RuntimeError("6.0 s source field directory is missing")
    control = destination / "system" / "controlDict"
    control_text = control.read_text(encoding="utf-8")
    control_text, start_from = re.subn(r"^startFrom\s+[^;]+;", "startFrom       startTime;", control_text,
                                       count=1, flags=re.MULTILINE)
    control_text, start_time = re.subn(r"^startTime\s+[^;]+;", f"startTime       {source_time};", control_text,
                                       count=1, flags=re.MULTILINE)
    if start_from != 1 or start_time != 1:
        raise RuntimeError("restart controlDict entries are missing or ambiguous")
    control.write_text(control_text, encoding="utf-8")
    motion = destination / "constant" / "dynamicMeshDict"
    motion_text = motion.read_text(encoding="utf-8")
    motion_text, motion_start = re.subn(r"(^\s*startTime\s+)[^;]+;", rf"\g<1>{source_time};", motion_text,
                                        count=1, flags=re.MULTILINE)
    if motion_start != 1:
        raise RuntimeError("ancfFileMotion restart startTime is missing or ambiguous")
    motion.write_text(motion_text, encoding="utf-8")
    config_path = destination / "multi_slice_case_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["case_id"] = f"{case_id}_slice_{slice_id:04d}"
    config["run_id"] = run_id
    config["start_time_s"] = SOURCE_TIME_S
    config_path.write_text(json.dumps(config, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    audit = {
        "stage_id": stage_id, "run_id": run_id, "case_id": case_id, "slice_id": slice_id,
        "source_time_s": SOURCE_TIME_S, "source_time_directory": source_time,
        "control_dict_start_from": "startTime", "control_dict_start_time_s": SOURCE_TIME_S,
        "ancf_file_motion_start_time_s": SOURCE_TIME_S, "old_bridge_removed": True,
        "only_source_and_zero_fields_retained_before_external_launch": True,
    }
    (destination / "continuation_restart_clock_audit.json").write_text(
        json.dumps(audit, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
