from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

DT_S = 0.000625
START_TIME_S = 1.5075
TARGET_TIME_S = 1.5081250000000002
RELAXATION_CANDIDATES = (0.25, 0.5)
MAX_ITERATIONS = 4
FORCE_ABSOLUTE_SCALE_N = 25000.0


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_contract(parent_sha256: str) -> dict[str, Any]:
    value = {
        "schema": "stage4f-c-fixed-point-diagnostic-v1-1.0.0",
        "parent_checkpoint_sha256": parent_sha256,
        "dt_s": DT_S,
        "start_time_s": START_TIME_S,
        "target_time_s": TARGET_TIME_S,
        "relaxation_candidates": list(RELAXATION_CANDIDATES),
        "max_iterations": MAX_ITERATIONS,
        "force_absolute_scale_N": FORCE_ABSOLUTE_SCALE_N,
        "same_parent_rollback_each_iteration": True,
        "openfoam_physical_steps_per_iteration": 1,
        "production_gate_claim": False,
    }
    value["contract_sha256"] = _hash(value)
    return value


def validate_contract(value: Mapping[str, Any]) -> None:
    copy = dict(value); supplied = copy.pop("contract_sha256", None)
    if supplied != _hash(copy):
        raise ValueError("contract hash mismatch")
    frozen = build_contract(str(value.get("parent_checkpoint_sha256")))
    if value != frozen:
        raise ValueError("fixed-point diagnostic contract changed")

