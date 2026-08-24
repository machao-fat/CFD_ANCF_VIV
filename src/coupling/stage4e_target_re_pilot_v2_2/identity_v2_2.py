"""Frozen identities and JSON/hash helpers for Stage 4E-B2-A-v2.2."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

PROJECT = Path(__file__).resolve().parents[3]
V2_1_RUN_ID = "20260815T145000000Z_stage4e_b2_a_v2_1_medium_screening"
V2_1_RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot_v2_1" / V2_1_RUN_ID
V2_1_CASES = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_1" / V2_1_RUN_ID
V2_1_RUNTIME = PROJECT / "runtime" / "stage4e_b2_a_v2_1" / V2_1_RUN_ID
FLOW_PROFILE_SHA256 = "28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e"
MANIFEST_SHA256 = "995e2cd958dda81ea00574187a7b189785f28d54266839debd11976bcd3a7860"
CONFIG_SHA256 = "fd847246d3e0ed00ec49d3a53644bd32651d6e185ac0cb7c33f91a8da056e677"
CASE_ID = "stage4e_v3_2_2_final_zero_aware_9"
CANDIDATE = "zero_crossing_aware_9_point_sampling"
D = 0.02841
RHO = 1000.0
NU = 1.0e-6
U_HIGH = 0.43414375179615955
RE_HIGH = 12334.023988528894
B_MESH = D
AREF = D * B_MESH
EPSILON = 0.005
WARMUP_END = 0.2
PRODUCTION_DT = 4.0e-4
HALF_PRODUCTION_DT = 2.0e-4
FIELD_INTERVAL_STEPS = 500
FORCE_INTERVAL_STEPS = 5
HARD_CFL = 0.8
PRODUCTION_CFL_TARGET = 0.5
STATISTICS_MIN_CYCLES = 15.0


def finite(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN/Inf is not allowed in v2.2 evidence")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(finite(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rows.append({"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(path)})
    return sha256_json(rows)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(finite(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
