from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.coupling.stage4d_campaign.developed_flow_v2 import audit_v2_flow_identity


ROOT = Path(__file__).resolve().parents[2]


class DevelopedFlowV2ArtifactTests(unittest.TestCase):
    def test_v2_bank_is_explicitly_blocked_or_ready_for_sol_review(self) -> None:
        bank = json.loads((ROOT / "results" / "06_developed_flow_v2" / "developed_flow_bank_v2.json").read_text(encoding="utf-8"))
        self.assertIn(bank["status"], {"blocked", "ready_for_sol_review"})
        self.assertTrue(bank["bank_identity_excludes_absolute_paths"])
        self.assertEqual(set(bank["flow_ids"]), {"re80", "re100", "re120"})

    def test_all_v2_flow_hashes_recompute(self) -> None:
        bank = json.loads((ROOT / "results" / "06_developed_flow_v2" / "developed_flow_bank_v2.json").read_text(encoding="utf-8"))
        for summary in bank["flows"]:
            result = audit_v2_flow_identity(
                summary,
                case=ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v2" / summary["flow_id"],
                result_dir=ROOT / "results" / "06_developed_flow_v2" / summary["flow_id"],
            )
            self.assertEqual(result["status"], "passed")

    def test_source_force_lineage_is_unchanged_and_no_setfields_in_continuation(self) -> None:
        for flow_id in ("re80", "re100", "re120"):
            lineage = json.loads((ROOT / "results" / "06_developed_flow_v2" / flow_id / "continuation_lineage.json").read_text(encoding="utf-8"))
            self.assertTrue(lineage["source_force_unchanged"])
            self.assertFalse(lineage["setFields_called"])
            self.assertEqual(lineage["startFrom"], "latestTime")
            self.assertFalse((ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v2" / flow_id / "0").exists())

    def test_real_overlap_peak_is_exactly_two(self) -> None:
        result = json.loads((ROOT / "results" / "06_developed_flow_v2" / "process_limiter_real_overlap_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["max_processes"], 2)
        self.assertEqual(result["peak_active_count"], 2)
        self.assertEqual(result["interval_peak_active_count"], 2)
        self.assertFalse(result["permit_leak"])
        self.assertFalse(result["sleep_used_to_create_overlap"])
        self.assertTrue(result["preflight_completed_before_solver_submission"])
        self.assertEqual(len(result["processes"]), 3)
        self.assertTrue(all(item["return_code"] == 0 and item["normal_end"] for item in result["processes"]))


if __name__ == "__main__":
    unittest.main()
