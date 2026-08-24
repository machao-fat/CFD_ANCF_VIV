from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import test_mapping  # noqa: E402


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_mapping)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "schema_version": "stage4_multislice_mapping_test_summary_0.2.1",
        "protocol_version": "0.2.1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "tests_run": result.testsRun,
        "tests_passed": result.testsRun - len(result.failures) - len(result.errors),
        "tests_failed": len(result.failures) + len(result.errors),
        "max_force_conversion_relative_error": test_mapping.METRICS["max_force_conversion_relative_error"],
        "max_virtual_work_absolute_error": test_mapping.METRICS["max_virtual_work_absolute_error"],
        "max_virtual_work_relative_error": test_mapping.METRICS["max_virtual_work_relative_error"],
        "permutation_test_pass": test_mapping.METRICS["permutation_test_pass"],
        "missing_slice_rejected": test_mapping.METRICS["missing_slice_rejected"],
        "duplicate_slice_rejected": test_mapping.METRICS["duplicate_slice_rejected"],
        "unexpected_slice_rejected": test_mapping.METRICS["unexpected_slice_rejected"],
        "nan_inf_rejected": test_mapping.METRICS["nan_inf_rejected"],
        "hash_tamper_rejected": test_mapping.METRICS["hash_tamper_rejected"],
        "delta_s_applied_once": test_mapping.METRICS["delta_s_applied_once"],
        "old_schema_rejected": test_mapping.METRICS["old_schema_rejected"],
        "golden_hash_repeat_pass": test_mapping.METRICS["golden_hash_repeat_pass"],
        "config_manifest_independent_pass": test_mapping.METRICS["config_manifest_independent_pass"],
        "status": "pass" if result.wasSuccessful() else "fail",
    }
    fixture_dir = HERE / "fixtures"
    hashes_path = fixture_dir / "golden_hashes_0.2.1.json"
    if hashes_path.is_file():
        summary["golden_hashes"] = json.loads(hashes_path.read_text(encoding="utf-8"))
    output = ROOT / "results" / "05_multi_slice_mapping_tests_v2" / "mapping_v2_summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
