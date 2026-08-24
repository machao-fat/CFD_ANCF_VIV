import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_three_slice_short_window_v1_repair2.runner import _log_audit


class TestRepairLogClassifier(unittest.TestCase):
    def classify(self, text, *, return_codes=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "solver.log"
            path.write_text(text, encoding="utf-8")
            return _log_audit([str(path)], return_codes=return_codes)

    @staticmethod
    def finite_log(extra=""):
        return (
            "sigFpe: Enabling floating point exception trapping (FOAM_SIGFPE)\n"
            "Courant Number mean: 0.1 max: 0.2\n"
            + extra + "\nEnd\n"
        )

    def test_sigfpe_startup_banner_is_normal(self):
        result = self.classify(self.finite_log())
        self.assertTrue(result["passed"])
        self.assertEqual(result["logs"][0]["failure_reasons"], [])

    def test_foam_fatal_and_fatal_io_are_rejected(self):
        for token in ("FOAM FATAL ERROR", "FOAM FATAL IO ERROR"):
            result = self.classify(self.finite_log(token))
            self.assertFalse(result["passed"])
            self.assertIn("foam_fatal", result["logs"][0]["failure_reasons"])

    def test_actual_floating_point_crash_is_rejected(self):
        result = self.classify(self.finite_log("Floating point exception"))
        self.assertFalse(result["passed"])
        self.assertIn("floating_point_crash", result["logs"][0]["failure_reasons"])

    def test_sigfpe_crash_variants_are_rejected(self):
        for token in ("received signal SIGFPE", "caught SIGFPE", "SIGFPE: abort"):
            result = self.classify(self.finite_log(token))
            self.assertFalse(result["passed"], token)
            self.assertIn("floating_point_crash", result["logs"][0]["failure_reasons"])

    def test_nonfinite_values_are_rejected_at_token_boundaries(self):
        for token in ("NaN", "+Inf", "-Inf"):
            result = self.classify(self.finite_log("field value = " + token))
            self.assertFalse(result["passed"], token)
            self.assertIn("nonfinite_token", result["logs"][0]["failure_reasons"])

    def test_words_are_not_nonfinite_tokens(self):
        result = self.classify(self.finite_log("information infiniteLoop"))
        self.assertTrue(result["passed"])

    def test_missing_end_is_rejected(self):
        result = self.classify(self.finite_log().replace("End\n", ""))
        self.assertFalse(result["passed"])
        self.assertFalse(result["logs"][0]["has_End"])

    def test_nonzero_return_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "solver.log"
            path.write_text(self.finite_log(), encoding="utf-8")
            result = _log_audit([str(path)], return_codes={str(path): 7})
        self.assertFalse(result["passed"])
        self.assertIn("nonzero_return_code", result["logs"][0]["failure_reasons"])

    def test_cfl_strict_boundary(self):
        self.assertTrue(self.classify(self.finite_log().replace("max: 0.2", "max: 0.799"))["passed"])
        self.assertFalse(self.classify(self.finite_log().replace("max: 0.2", "max: 0.8"))["passed"])

    def test_negative_volume_is_rejected(self):
        result = self.classify(self.finite_log("minimum negative volume = -1e-4"))
        self.assertFalse(result["passed"])
        self.assertIn("negative_volume", result["logs"][0]["failure_reasons"])

    def test_any_failed_slice_blocks_global_step(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, extra in enumerate(("", "FOAM FATAL ERROR", "")):
                path = Path(directory) / f"slice_{index}.log"
                path.write_text(self.finite_log(extra), encoding="utf-8")
                paths.append(str(path))
            audit = _log_audit(paths)
        self.assertFalse(audit["passed"])
        self.assertFalse(all(row["passed"] for row in audit["logs"]))

    def test_old_attempt2_logs_reclassify_as_passed(self):
        root = Path(__file__).resolve().parents[2]
        log_root = root / "cases/openfoam/stage4f_three_slice_short_window_v1/formal_attempt2_20260817T101500Z_6f31c4a2/branch_A/segment_20/cases"
        paths = [str(log_root / f"slice_{index:04d}" / f"log.pimpleFoam_stage4f_c_v1_a_slice_{index:04d}_step00000000") for index in range(3)]
        result = _log_audit(paths, return_codes=[0, 0, 0])
        self.assertTrue(result["passed"])
        self.assertEqual(result["max_cfl"], 0.1363182835702355)
        self.assertTrue(all(row["has_End"] for row in result["logs"]))


if __name__ == "__main__":
    unittest.main()
