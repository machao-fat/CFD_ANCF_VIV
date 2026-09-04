from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_to70s_integration_v1.integration import (
    IntegrationError, MappingContract, OfflineThreeSliceCampaign,
)


class OfflineIntegrationTests(unittest.TestCase):
    def test_mapping_559_style_source_to_target_is_explicit(self) -> None:
        mapping = MappingContract(source_step=559, source_time_s=2.2075,
                                  target_step=560, slice_count=3)
        mapping.validate(global_step=560, bridge_step=1, time_s=2.20875,
                         integer_tick=2_208_750_000)
        with self.assertRaises(IntegrationError):
            mapping.validate(global_step=560, bridge_step=560, time_s=2.20875,
                             integer_tick=2_208_750_000)

    def test_three_slice_barrier_and_rolling_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = OfflineThreeSliceCampaign(
                runtime=root / "runtime", results=root / "results",
                run_id="run220", case_id="case220")
            result = campaign.run(120)
            self.assertEqual(result["commit_count"], 120)
            self.assertEqual(result["barrier_count"], 120)
            self.assertEqual(result["slice_ack_count"], 360)
            self.assertEqual(result["case_entries_per_slice"], [41, 41, 41])
            self.assertEqual(result["checkpoint_count"], 40)
            self.assertEqual(result["exchange_artifact_count"], 40)
            self.assertEqual(result["restart"]["global_step"], 120)
            self.assertEqual(result["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
            self.assertEqual(result["owned_residual"], 0)

    def test_stale_ack_and_tick_mismatch_fail_closed(self) -> None:
        mapping = MappingContract()
        with self.assertRaises(IntegrationError):
            mapping.validate(global_step=2, bridge_step=2, time_s=0.0025,
                             integer_tick=2_500_001)
        with self.assertRaises(IntegrationError):
            mapping.validate(global_step=2, bridge_step=1, time_s=0.0025,
                             integer_tick=2_500_000)

    def test_duplicate_or_out_of_order_step_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = OfflineThreeSliceCampaign(
                runtime=root / "runtime", results=root / "results",
                run_id="run220", case_id="case220")
            campaign._materialize_source()
            campaign.commit_one(1)
            with self.assertRaises(IntegrationError):
                campaign.commit_one(1)
            with self.assertRaises(IntegrationError):
                campaign.commit_one(3)


if __name__ == "__main__":
    unittest.main()
