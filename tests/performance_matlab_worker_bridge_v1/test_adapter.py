from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.performance_matlab_worker_bridge_v1.adapter import PersistentMatlabCampaignAdapter, CampaignAdapterError


class AdapterTests(unittest.TestCase):
    def test_campaign_lifecycle_uses_one_worker_for_prediction_and_correction(self):
        adapter = PersistentMatlabCampaignAdapter(work_dir=Path(tempfile.mkdtemp()), start_time_s=2.2075, manifest=None)
        adapter.start()
        for step in range(560, 600):
            time_s = 2.2075 + (step - 559) * .00125
            adapter.predict(step, time_s, [[0.0, 0.0, 0.0]] * 3)
            adapter.correct(step, time_s, [[0.0, 0.0, 0.0]] * 3)
            adapter.finalize_committed()
        self.assertEqual(adapter.worker_start_count, 1)
        self.assertEqual(len(adapter.operation_audit), 80)
        adapter.shutdown()
        self.assertEqual(adapter.owned_residual, 0)

    def test_correction_without_prediction_fails_closed(self):
        adapter = PersistentMatlabCampaignAdapter(work_dir=Path(tempfile.mkdtemp()), start_time_s=2.2075, manifest=None)
        adapter.start()
        with self.assertRaises(CampaignAdapterError):
            adapter.correct(560, 2.20875, [[0.0, 0.0, 0.0]] * 3)
        adapter.shutdown()


if __name__ == "__main__":
    unittest.main()
