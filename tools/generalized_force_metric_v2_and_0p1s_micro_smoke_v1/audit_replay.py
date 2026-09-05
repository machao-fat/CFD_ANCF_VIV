"""Apply the frozen V2 criterion to immutable generalized-force replays."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.generalized_force_metric_v2 import evaluate, freeze_contract  # noqa: E402

SOURCE = ROOT / "results/generalized_force_mismatch_root_cause_audit_v1/generalized_force_replay_v1_summary.json"
OUT = ROOT / "results/generalized_force_metric_v2_and_0p1s_micro_smoke_v1/replay_v2_audit.json"


def assess(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    contributions = [item["Q_formal_N"] for item in row["per_slice"]]
    metric = evaluate(row["Q_formal_N"], row["Q_cpp_N"], contributions, contract=contract)
    return {"name": row["name"], "metric": metric,
            "source_fixture_sha256": row.get("fixture_sha256"),
            "source_cpp_output_sha256": row.get("cpp_output_sha256")}


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    contract = freeze_contract(50.0 / 16.0)
    items = [assess(item, contract) for item in source["committed_replays"] + source["synthetic_matrix"]]
    report = {"schema_version": "generalized-force-metric-v2-replay-audit.1",
              "source_summary": str(SOURCE.relative_to(ROOT)), "metric_contract": contract,
              "items": items,
              "GENERALIZED_FORCE_METRIC_V2_CONTRACT": "PASS" if all(item["metric"]["GENERALIZED_FORCE_MAPPING_V2"] == "PASS" for item in items) else "FAIL",
              "max_absolute_error": max(item["metric"]["max_absolute_error"] for item in items),
              "max_threshold_utilization": max(item["metric"]["max_threshold_utilization"] for item in items),
              "max_normalized_error": max(item["metric"]["max_normalized_error"] for item in items)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("GENERALIZED_FORCE_METRIC_V2_CONTRACT", "max_absolute_error", "max_threshold_utilization")}))
    return 0 if report["GENERALIZED_FORCE_METRIC_V2_CONTRACT"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
