"""Frozen Stage 4E-A identity and finite JSON helpers for B2-A."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
FLOW_PATH = ROOT / "results" / "08_stage4e_physical_baseline_v3_2_2" / "route_G_flow_profile_candidate.json"
EXPECTED_FLOW_PROFILE_SHA256 = "28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e"
EXPECTED_MANIFEST_SHA256 = "995e2cd958dda81ea00574187a7b189785f28d54266839debd11976bcd3a7860"
EXPECTED_CONFIG_SHA256 = "fd847246d3e0ed00ec49d3a53644bd32651d6e185ac0cb7c33f91a8da056e677"
EXPECTED_CASE_ID = "stage4e_v3_2_2_final_zero_aware_9"
EXPECTED_CANDIDATE = "zero_crossing_aware_9_point_sampling"


def finite(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN/Inf is not allowed in B2-A evidence")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        finite(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def formal_flow_identity(flow: Mapping[str, Any]) -> str:
    """Reproduce the parent Route-G hash over its identity content only."""
    keys = (
        "schema_version", "case_id", "protocol_version", "selected_candidate",
        "slice_geometry_sha256", "slice_manifest_sha256", "source_profile_sha256",
        "benchmark_Umax_mps", "diameter_m", "kinematic_viscosity_m2ps", "slices",
    )
    return sha256_json({key: flow[key] for key in keys})


def load_formal_flow_profile(path: Path = FLOW_PATH) -> dict[str, Any]:
    flow = read_json(path)
    if flow.get("case_id") != EXPECTED_CASE_ID:
        raise ValueError("parent flow profile case_id is not the frozen nine-slice identity")
    if flow.get("selected_candidate") != EXPECTED_CANDIDATE:
        raise ValueError("parent flow profile candidate is not the frozen nine-slice candidate")
    if len(flow.get("slices", [])) != 9:
        raise ValueError("parent flow profile must contain nine slices")
    if flow.get("flow_profile_sha256") != EXPECTED_FLOW_PROFILE_SHA256:
        raise ValueError("parent flow profile hash changed")
    # The v3.2.2 artifact's hash is defined over the identity subset above.
    if formal_flow_identity(flow) != EXPECTED_FLOW_PROFILE_SHA256:
        raise ValueError("parent flow profile canonical identity cannot be reproduced")
    if flow.get("slice_manifest_sha256") != EXPECTED_MANIFEST_SHA256:
        raise ValueError("parent manifest hash mismatch")
    return flow


def choose_representative_cases(flow: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entries = [item for item in flow["slices"] if bool(item.get("active", True))]
    nonzero = [item for item in entries if abs(float(item["signed_U_global_mps"])) > 0.0]
    low = min(nonzero, key=lambda item: abs(float(item["signed_U_global_mps"])))
    high = max(nonzero, key=lambda item: abs(float(item["signed_U_global_mps"])))
    middle = sorted(nonzero, key=lambda item: abs(float(item["signed_U_global_mps"])))
    mid = middle[(len(middle) - 1) // 2]
    out: dict[str, dict[str, Any]] = {}
    for label, item in (("low", low), ("middle", mid), ("high", high)):
        speed = abs(float(item["signed_U_global_mps"]))
        out[label] = {
            "label": label,
            "source_slice_id": int(item["slice_id"]),
            "source_s_ref_m": float(item["s_ref_m"]),
            "source_signed_U_global_mps": float(item["signed_U_global_mps"]),
            "source_flow_sign": int(item["flow_sign"]),
            "pilot_U_mps": speed,
            "diameter_m": float(flow["diameter_m"]),
            "kinematic_viscosity_m2ps": float(flow["kinematic_viscosity_m2ps"]),
            "Re": speed * float(flow["diameter_m"]) / float(flow["kinematic_viscosity_m2ps"]),
            "pilot_direction_policy": "positive_equivalent_magnitude; Route-G reverse sign is covered by B1 smoke",
        }
    return out
