from __future__ import annotations

import sys
import shutil
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_confirm_v1.contracts import CppConfirmContract, ContractError, REAL_AUTHORIZATION_TOKEN
from tools.cpp_worker_long_window_v1 import run_authorized_long_window_001 as window


class LongWindowContractTests(unittest.TestCase):
    def _contract(self, *, steps: int = window.AUTHORIZED_STEPS,
                  duration: float = 1.0, source_step: int = window.SOURCE_STEP) -> CppConfirmContract:
        return CppConfirmContract(
            stage_id=window.STAGE_ID, run_id="long_window_contract_test", case_id="long_window_contract_case",
            runtime=PROJECT / "runtime/test_cpp_worker_long_window_contract/runtime",
            results=PROJECT / "results/test_cpp_worker_long_window_contract",
            source_checkpoint=window.SOURCE, source_checkpoint_sha256=window.SOURCE_SHA256,
            source_global_step=source_step,
            source_time_s=window.SOURCE_TIME_S,
            source_tick=window.SOURCE_TICK,
            steps=steps, segment_duration_s=duration, global_dt_s=window.DT_S,
            slice_count=3, allow_real_external_processes=True,
            authorization=REAL_AUTHORIZATION_TOKEN,
        )

    def test_exact_authorized_mapping_and_source_checkpoint_validate(self) -> None:
        contract = self._contract()
        contract.validate(PROJECT)
        self.assertEqual(window.TARGET_STEP, 1439)
        self.assertAlmostEqual(window.TARGET_TIME_S, 3.3075)
        self.assertEqual(window.TARGET_TICK, 3_307_500_000)
        self.assertEqual(window.KEEP_FROM_STEP, 1400)

    def test_any_scope_expansion_or_shift_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            self._contract(steps=801, duration=1.00125).validate(PROJECT)
        with self.assertRaises(ContractError):
            self._contract(source_step=640).validate(PROJECT)

    def test_only_three_slices_and_unchanged_dt_are_allowed(self) -> None:
        contract = self._contract()
        self.assertEqual(contract.slice_count, 3)
        self.assertEqual(contract.global_dt_s, 0.00125)
        self.assertEqual(window.AUTHORIZED_STEPS * window.DT_S, 1.0)
        self.assertEqual(window.KEEP_FULL_STEPS, 40)

    def test_retention_policy_preserves_source_and_final_window(self) -> None:
        self.assertLess(window.SOURCE_TIME_S, window.KEEP_FROM_TIME_S)
        self.assertAlmostEqual(window.KEEP_FROM_TIME_S, 3.25875)
        self.assertEqual(window.TARGET_STEP - window.KEEP_FROM_STEP + 1, 40)
        self.assertIn("retention_predelete_manifest.json", window._post_success_retention.__code__.co_consts)

    def test_restart_clock_is_rewritten_before_external_launch(self) -> None:
        template = window.TEMPLATE_ROOT / "slice_0000"
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "slice_0000"
            (destination / "system").mkdir(parents=True)
            (destination / "constant").mkdir(parents=True)
            shutil.copy2(template / "system" / "controlDict", destination / "system" / "controlDict")
            shutil.copy2(template / "constant" / "dynamicMeshDict", destination / "constant" / "dynamicMeshDict")
            shutil.copy2(template / "multi_slice_case_config.json", destination / "multi_slice_case_config.json")
            (destination / format(window.SOURCE_TIME_S, ".12g")).mkdir()
            window._rewrite_restart_clock(destination, slice_id=0)
            control = (destination / "system" / "controlDict").read_text(encoding="utf-8")
            self.assertIn("startFrom       startTime;", control)
            self.assertIn("startTime       2.3075;", control)
            motion = (destination / "constant" / "dynamicMeshDict").read_text(encoding="utf-8")
            self.assertIn("startTime       2.3075;", motion)
            audit = destination / "continuation_restart_clock_audit.json"
            self.assertTrue(audit.is_file())


if __name__ == "__main__":
    unittest.main()
