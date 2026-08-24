"""Disk-derived audit independent of runner pass claims."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import sha256_file

SHA = re.compile(r"^[0-9a-f]{64}$")


class DiskAuditError(ValueError): pass


def audit_step(row: Mapping[str, Any], *, case_block_root: Path) -> dict[str, Any]:
    step = int(row["physical_step"]); selected = int(row["selected_iteration"])
    step_root = case_block_root / f"step_{step:02d}"
    committed = []
    for path in step_root.glob("iteration_*/checkpoints/checkpoint_*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") == "committed": committed.append((path.resolve(), payload))
    if len(committed) != 1:
        raise DiskAuditError(f"step {step} has {len(committed)} committed checkpoints")
    path, payload = committed[0]
    if path != Path(row["checkpoint"]).resolve() or f"iteration_{selected:02d}" not in path.parts:
        raise DiskAuditError("selected iteration/checkpoint path mismatch")
    iteration = row["iterations"][selected]
    if not iteration.get("final_candidate") or iteration.get("final_Cd_acceptance") is not True or int(iteration.get("residual_consecutive_count", 0)) < 2:
        raise DiskAuditError("selected candidate lacks frozen final acceptance")
    structure = payload.get("structure", {})
    runner_hash = structure.get("runner_checkpoint_sha256")
    if not isinstance(runner_hash, str) or not SHA.fullmatch(runner_hash):
        raise DiskAuditError("runner checkpoint SHA-256 is missing")
    slices = payload.get("slices")
    if not isinstance(slices, list) or sorted(int(x["slice_id"]) for x in slices) != [0, 1, 2]:
        raise DiskAuditError("slice identities are not exactly 0/1/2")
    keys = []
    for slice_row in slices:
        sid = int(slice_row["slice_id"])
        for group in ("static_files", "time_files"):
            for field in slice_row.get(group, []):
                digest = field.get("sha256"); key = (sid, group, field.get("relative_path"))
                if not isinstance(digest, str) or not SHA.fullmatch(digest): raise DiskAuditError("invalid CFD field hash")
                keys.append(key)
    if len(keys) != 24 or len(set(keys)) != 24:
        raise DiskAuditError("CFD field identities are not 24 unique entries")
    if sha256_file(path) != row["checkpoint_sha256"]:
        raise DiskAuditError("checkpoint SHA differs from summary")
    return {"step": step, "checkpoint": str(path), "checkpoint_sha256": row["checkpoint_sha256"], "selected_iteration": selected, "runner_checkpoint_sha256": runner_hash, "unique_cfd_fields": 24, "slice_ids": [0,1,2], "passed": True}


def audit_block(block: Mapping[str, Any], *, case_block_root: Path, expected_start: int, expected_end: int) -> dict[str, Any]:
    if block.get("status") != "passed" or int(block.get("committed_steps", -1)) != expected_end - expected_start:
        raise DiskAuditError("block summary did not pass all requested steps")
    processes = block.get("processes", {})
    if processes.get("started") != processes.get("closed") or int(processes.get("residual", -1)) != 0 or int(processes.get("nonzero_return_codes", -1)) != 0:
        raise DiskAuditError("block process closeout failed")
    rows = block.get("steps", [])
    if [int(x["physical_step"]) for x in rows] != list(range(expected_start, expected_end)):
        raise DiskAuditError("block step schedule mismatch")
    audited = [audit_step(row, case_block_root=case_block_root) for row in rows]
    return {"status": "passed", "expected_range": [expected_start, expected_end], "steps": audited, "processes": processes}
