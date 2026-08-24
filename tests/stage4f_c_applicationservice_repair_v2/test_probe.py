import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_c_applicationservice_repair_v2.probe import (
    SCHEMA, build_isolated_environment, payload_expression, validate_payload,
)


class TestApplicationServiceRepair2Offline(unittest.TestCase):
    def test_payload_expression_is_structured_and_tokenized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.json"
            expression = payload_expression(run_id="run1", token="token1", payload_path=path)
        self.assertIn(SCHEMA, expression)
        self.assertIn("jsonencode(probe)", expression)
        self.assertIn("MATLAB_PROBE_PAYLOAD_WRITTEN", expression)

    def test_isolated_environment_is_on_d_drive_runtime(self):
        with tempfile.TemporaryDirectory(dir="D:\\") as directory:
            env = build_isolated_environment(Path(directory))
        for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR", "MATLAB_PREFDIR", "MATLAB_LOG_DIR"):
            self.assertTrue(str(env[key]).lower().startswith("d:"), (key, env[key]))

    def test_payload_requires_application_service_and_zero_return(self):
        with tempfile.TemporaryDirectory(dir="D:\\") as directory:
            run = Path(directory)
            good = {
                "schema_version": SCHEMA, "run_id": "run1", "run_token": "token1",
                "probe_begin": True, "probe_end": True, "version": "9.11.0.1837725 (R2021b)",
                "release": "2021b", "architecture": "win64", "license_test_matlab": 1,
                "TEMP": str(run / "tmp"), "TMP": str(run / "tmp"), "TMPDIR": str(run / "tmpdir"),
                "tempdir": str(run / "tmp"), "prefdir": str(run / "matlab_pref"), "pwd": str(run),
                "application_service": "ok",
            }
            self.assertTrue(validate_payload(good, run=run, run_id="run1", token="token1", return_code=0)["all_checks_passed"])
            bad = dict(good, application_service="error 5001")
            self.assertFalse(validate_payload(bad, run=run, run_id="run1", token="token1", return_code=0)["all_checks_passed"])
            self.assertFalse(validate_payload(good, run=run, run_id="run1", token="token1", return_code=1)["all_checks_passed"])


if __name__ == "__main__":
    unittest.main()
