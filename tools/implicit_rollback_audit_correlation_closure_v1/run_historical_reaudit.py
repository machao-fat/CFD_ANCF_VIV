"""Read-only corrected rollback re-audit of the immutable two-window runtime."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.implicit_rollback_audit_correlation_v1 import correlate_rollback_trace

RUN = "implicit_cross_window_ipc_lifecycle_closure_v1_formal_two_window_001"


def main() -> int:
    source = ROOT / "runtime" / RUN
    target = ROOT / "results" / "implicit_rollback_audit_correlation_closure_v1_historical_reaudit_001"
    if target.exists():
        raise RuntimeError(f"refusing to overwrite immutable result {target}")
    target.mkdir(parents=True)
    slices: dict[str, object] = {}
    for sid in range(3):
        trace = [json.loads(line) for line in (source / f"fluid_{sid:04d}_adapter_trace.jsonl").read_text(encoding="utf-8").splitlines()]
        slices[str(sid)] = correlate_rollback_trace(trace)
    failures = [f"slice {sid}: {error}" for sid, value in slices.items()
                for error in value.get("errors", [])]
    result = {
        "schema_version": "implicit-rollback-audit-correlation-v1",
        "immutable_source_runtime": str(source),
        "original_FORMAL_IMPLICIT_TWO_WINDOW": "FAIL (immutable)",
        "HISTORICAL_TWO_WINDOW_CORRECTED_REAUDIT": "PASS" if not failures else "FAIL",
        "slices": slices,
        "first_blocker": failures[0] if failures else None,
    }
    (target / "historical_two_window_corrected_reaudit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("HISTORICAL_TWO_WINDOW_CORRECTED_REAUDIT", "first_blocker")}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
