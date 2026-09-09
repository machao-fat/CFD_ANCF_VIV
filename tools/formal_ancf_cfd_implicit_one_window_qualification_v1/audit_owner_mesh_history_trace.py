#!/usr/bin/env python3
"""Read-only supplemental trace audit for owner-managed mesh-history diagnostics.

This does not replace the frozen formal rollback auditor.  It merely compares
the owner-owned state recorded under ``states.owner_mesh_history`` with the
same checkpoint generation at every restore in a runtime that used the
owner-observability adapter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


TOP_LEVEL_STATE_KEYS = (
    "U", "p", "phi", "Uf", "pointDisplacement", "cellDisplacement", "mesh_points",
)
OWNER_STATE_KEYS = (
    "moving", "cur_motion_time_index", "cur_time_index", "store_old_cell_centres",
    "old_points", "old_cell_centres", "V0", "V00", "meshPhi",
)


def load_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def compare(checkpoint: dict, restore: dict) -> list[str]:
    differences: list[str] = []
    if checkpoint["physical_time"] != restore["physical_time"]:
        differences.append("physical_time")
    if checkpoint["time_index"] != restore["time_index"]:
        differences.append("time_index")
    checkpoint_states = checkpoint["states"]
    restore_states = restore["states"]
    for key in TOP_LEVEL_STATE_KEYS:
        if checkpoint_states.get(key) != restore_states.get(key):
            differences.append(key)
    checkpoint_owner = checkpoint_states.get("owner_mesh_history")
    restore_owner = restore_states.get("owner_mesh_history")
    if not isinstance(checkpoint_owner, dict) or not isinstance(restore_owner, dict):
        differences.append("owner_mesh_history_absent")
    else:
        for key in OWNER_STATE_KEYS:
            if checkpoint_owner.get(key) != restore_owner.get(key):
                differences.append(f"owner_mesh_history.{key}")
    return differences


def audit_slice(path: Path) -> dict:
    generations: list[dict] = []
    pairs: list[dict] = []
    for line_number, event in enumerate(load_trace(path), start=1):
        if event.get("event") == "CHECKPOINT_WRITE":
            generations.append({"line_number": line_number, "event": event})
        elif event.get("event") == "POST_ROLLBACK_BEFORE_NEXT_INPUT":
            candidates = [g for g in generations if g["line_number"] < line_number]
            if not candidates:
                pairs.append({"restore_line": line_number, "pass": False, "error": "restore_without_checkpoint"})
                continue
            generation = candidates[-1]
            differences = compare(generation["event"], event)
            pairs.append({
                "checkpoint_line": generation["line_number"],
                "restore_line": line_number,
                "physical_time": event["physical_time"],
                "time_index": event["time_index"],
                "pass": not differences,
                "differences": differences,
            })
    return {
        "trace": str(path),
        "generation_count": len(generations),
        "restore_pair_count": len(pairs),
        "restore_pairs": pairs,
        "status": "PASS" if pairs and all(pair.get("pass") for pair in pairs) else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    slices = {}
    for trace in sorted(args.runtime.glob("fluid_*_adapter_trace.jsonl")):
        slices[trace.name] = audit_slice(trace)
    result = {
        "schema_version": "owner-mesh-history-supplemental-read-only-audit-v1",
        "scope": "supplemental evidence only; does not replace frozen formal auditor",
        "slices": slices,
        "status": "PASS" if slices and all(value["status"] == "PASS" for value in slices.values()) else "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
