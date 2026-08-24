from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.coordinator import ConfirmError, Mapping, MockSlice, run_mock_confirm


class CppConfirmTests(unittest.TestCase):
    def test_mapping_is_explicit_for_source_559_to_560(self) -> None:
        bridge, time_s, tick = Mapping().identity(560)
        self.assertEqual((bridge, tick), (1, 2_208_750_000))
        self.assertAlmostEqual(time_s, 2.20875)

    def test_confirm_is_exactly_bounded_to_forty_steps(self) -> None:
        with self.assertRaises(ConfirmError):
            run_mock_confirm(runtime=Path(tempfile.mkdtemp()), steps=39)

    def test_slice_rejects_stale_time_and_tick(self) -> None:
        item = MockSlice(0, Mapping()); item.start()
        with self.assertRaises(ConfirmError):
            item.advance(global_step=560, time_s=2.2075, tick=2_207_500_000, q=(0.0, 0.0, 0.0, 0.0))
        item.stop()

    def test_slice_rejects_duplicate_lifecycle_start(self) -> None:
        item = MockSlice(1, Mapping()); item.start()
        with self.assertRaises(ConfirmError):
            item.start()

    def test_mock_confirm_has_one_worker_and_three_slice_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            gate = run_mock_confirm(runtime=runtime, results_dir=runtime / "evidence")
            self.assertTrue(gate["gate"].endswith("pass"))
            self.assertEqual(gate["physical_committed"], 40)
            self.assertEqual(gate["fully_audited"], 40)
            self.assertEqual(gate["worker_start_count"], 1)
            self.assertEqual(gate["slice_start_counts"], [1, 1, 1])
            self.assertEqual(gate["owned_residual"], 0)
            result = json.loads((runtime / "evidence" / "mock_confirm_result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["step_records"][0]["global_step"], 560)
            self.assertEqual(result["step_records"][-1]["global_step"], 599)
            self.assertEqual(result["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})


if __name__ == "__main__":
    unittest.main()
