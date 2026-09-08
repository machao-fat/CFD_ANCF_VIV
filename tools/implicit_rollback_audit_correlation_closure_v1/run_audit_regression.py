"""No-CFD positive/negative regression for rollback-generation correlation."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.implicit_rollback_audit_correlation_v1 import correlate_rollback_trace


def state(tag: str) -> dict[str, object]:
    fields = {name: {"classification": "PERSISTENT_RESTORED", "finite": True,
                     "canonical_hash_fnv1a64": f"{tag}-{name}", "old_time_levels": 0}
              for name in ("U", "p", "phi", "Uf", "pointDisplacement", "cellDisplacement", "mesh_points", "old_points")}
    fields["meshPhi"] = {"classification": "PERSISTENT_RESTORED", "finite": True,
                         "canonical_hash_fnv1a64": f"{tag}-meshPhi", "old_time_levels": 0}
    return fields


def event(kind: str, window: int, time: float, index: int, tag: str) -> dict[str, object]:
    return {"event": kind, "window_id": window, "physical_time": time, "time_index": index,
            "adapter_build_sha256": "adapter", "states": state(tag)}


def passed(trace: list[dict[str, object]]) -> bool:
    return correlate_rollback_trace(trace)["status"] == "PASS"


def main() -> int:
    c0 = event("CHECKPOINT_WRITE", 1, 0.1, 0, "a")
    r0 = event("POST_ROLLBACK_BEFORE_NEXT_INPUT", 1, 0.1, 0, "a")
    c1 = event("CHECKPOINT_WRITE", 1, 0.105, 1, "b")
    r1 = event("POST_ROLLBACK_BEFORE_NEXT_INPUT", 2, 0.105, 1, "b")
    cases: dict[str, bool] = {
        "single_window_single_checkpoint": passed([c0, r0]),
        "repeated_adapter_window_id": passed([c0, r0, c1, r1]),
        "same_checkpoint_multiple_restore": passed([c0, r0, deepcopy(r0)]),
        "next_checkpoint_overrides_old_generation": passed([c0, r0, c1, r1]),
        "missing_checkpoint_rejected": not passed([r0]),
        "restore_before_checkpoint_rejected": not passed([r0, c0]),
        "wrong_time_index_rejected": not passed([c0, event("POST_ROLLBACK_BEFORE_NEXT_INPUT", 1, 0.1, 1, "a")]),
        "ambiguous_event_sequence_rejected": not passed([dict(c0, event_sequence=1), dict(r0, event_sequence=1)]),
        "fingerprint_mismatch_rejected": not passed([c0, event("POST_ROLLBACK_BEFORE_NEXT_INPUT", 1, 0.1, 0, "wrong")]),
    }
    result = {"ROLLBACK_AUDIT_CORRELATION_REGRESSION": "PASS" if all(cases.values()) else "FAIL", "cases": cases}
    target = ROOT / "results" / "implicit_rollback_audit_correlation_closure_v1_regression_001"
    if target.exists():
        raise RuntimeError(f"refusing to overwrite immutable result {target}")
    target.mkdir(parents=True)
    (target / "rollback_audit_correlation_regression.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ROLLBACK_AUDIT_CORRELATION_REGRESSION"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
