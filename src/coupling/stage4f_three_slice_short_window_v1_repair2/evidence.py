"""Read-only parent protection and deterministic evidence helpers."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .contract import PARENT_CASE_ROOT, PARENT_CHECKPOINT, PROJECT_ROOT

PARENT_EVIDENCE = (
    PROJECT_ROOT / "results/12_stage4f_fixed_point_v5/stage4f_b_v5_gate_candidate.json",
    PROJECT_ROOT / "results/12_stage4f_fixed_point_v5/stage4f_b_v5_force_and_checkpoint_audit.json",
    PROJECT_ROOT / "cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/formal_preflight_summary.json",
    PROJECT_ROOT / "cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/restart_one_plus_two_attempt1/restart_one_plus_two_summary.json",
    PROJECT_ROOT / "docs/12_stage4f_b_v5_three_slice_preflight_gate.md",
)
FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _combined(rows: Iterable[Mapping[str, Any]]) -> str:
    text = "\n".join(f"{row['relative_path']} {row['sha256']}" for row in sorted(rows, key=lambda item: item["relative_path"]))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parent_protection_audit() -> dict[str, Any]:
    checkpoint = json.loads(PARENT_CHECKPOINT.read_text(encoding="utf-8"))
    paths = list(PARENT_EVIDENCE) + [PARENT_CHECKPOINT]
    structure_root = PARENT_CHECKPOINT.parent
    paths.extend(structure_root / str(checkpoint["structure"][name]) for name in ("checkpoint_relative_path", "runner_checkpoint_relative_path"))
    for entry in checkpoint["slices"]:
        case = PARENT_CASE_ROOT / str(entry["case_relative_path"])
        paths.extend(case / str(item["relative_path"]) for item in list(entry["static_files"]) + list(entry["time_files"]))
    unique = sorted({path.resolve() for path in paths}, key=lambda path: str(path).lower())
    rows = []
    for path in unique:
        if not path.is_file():
            raise FileNotFoundError(path)
        rows.append({"relative_path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if len(rows) != 32:
        raise RuntimeError(f"parent protection set changed: expected 32, got {len(rows)}")
    return {
        "status": "passed", "protected_file_count": len(rows), "files": rows,
        "combined_sha256": _combined(rows),
        "parent_checkpoint": str(PARENT_CHECKPOINT),
        "parent_checkpoint_sha256": sha256_file(PARENT_CHECKPOINT),
    }


def compare_parent_audits(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    passed = before.get("combined_sha256") == after.get("combined_sha256") and before.get("files") == after.get("files")
    return {"status": "passed" if passed else "blocked", "before_combined_sha256": before.get("combined_sha256"), "after_combined_sha256": after.get("combined_sha256"), "unchanged": passed}


def numeric_tokens(path: Path) -> list[float]:
    values = [float(item) for item in FLOAT_RE.findall(path.read_text(encoding="utf-8", errors="strict"))]
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"non-finite numeric token in {path}")
    return values


def numeric_file_comparison(left: Path, right: Path, *, absolute_scale: float = 1.0) -> dict[str, Any]:
    left_hash, right_hash = sha256_file(left), sha256_file(right)
    a, b = numeric_tokens(left), numeric_tokens(right)
    same_count = len(a) == len(b) and bool(a)
    error = max((abs(x-y) / max(absolute_scale, abs(x), abs(y)) for x, y in zip(a, b)), default=None) if same_count else None
    return {"left": str(left), "right": str(right), "sha256_equal": left_hash == right_hash, "left_sha256": left_hash, "right_sha256": right_hash, "numeric_token_count_equal": same_count, "numeric_token_count": len(a) if same_count else None, "max_relative_error": error}


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write_json(path, dict(value))
