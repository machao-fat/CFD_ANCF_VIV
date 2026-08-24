from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_c_probe_repair_v1.contract import (
    SCHEMA, read_json_payload, validate_payload,
)


class ProbeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Path(tempfile.gettempdir()) / "stage4f-c-probe" / "run"
        root = self.runtime.as_posix()
        self.value = {
            "schema_version": SCHEMA, "run_id": "run", "run_token": "token",
            "probe_begin": True, "probe_end": True, "version": "9.11.0 (R2021b)",
            "release": "2021b", "architecture": "win64", "license_test_matlab": 1,
            "TEMP": root + "/tmp", "TMP": root + "/tmp", "TMPDIR": root + "/tmp",
            "tempdir": root + "/tmp", "prefdir": root + "/matlab_pref", "pwd": root,
            "application_service": "ok",
        }

    def check(self, value=None, code=0, console=""):
        return validate_payload(value or self.value, runtime_root=self.runtime, return_code=code,
            run_id="run", run_token="token", executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe", console_text=console)

    def test_correct_payload(self): self.assertTrue(self.check()["all_checks_passed"])
    def test_variable_name_error(self):
        value = dict(self.value); value["release_R2021b"] = value.pop("release")
        self.assertFalse(self.check(value)["all_checks_passed"])
    def test_missing_field(self):
        value = dict(self.value); del value["architecture"]
        self.assertFalse(self.check(value)["all_checks_passed"])
    def test_release_formats_are_strict(self):
        for release in ("R2021b", "release_R2021b"):
            value = dict(self.value); value["release"] = release
            self.assertFalse(self.check(value)["all_checks_passed"])
    def test_license_zero_and_return_code_nonzero(self):
        value = dict(self.value); value["license_test_matlab"] = 0
        self.assertFalse(self.check(value)["all_checks_passed"])
        self.assertFalse(self.check(code=1)["all_checks_passed"])
    def test_nan_and_infinity(self):
        for number in (float("nan"), float("inf"), float("-inf")):
            value = dict(self.value); value["diagnostic"] = number
            self.assertFalse(self.check(value)["all_checks_passed"])
    def test_c_drive_temp_tmp_tmpdir_prefdir(self):
        for key in ("TEMP", "TMP", "TMPDIR", "tempdir", "prefdir"):
            value = dict(self.value); value[key] = r"C:\Users\Administrator\AppData\Local\Temp\probe"
            self.assertFalse(self.check(value)["all_checks_passed"], key)
    def test_payload_console_mismatch(self):
        console = 'PROBE_PAYLOAD_JSON=' + json.dumps({**self.value, "release": "R2021b"})
        self.assertFalse(self.check(console=console)["all_checks_passed"])
    def test_launcher_success_but_matlab_internal_failure(self):
        value = dict(self.value); value["application_service"] = "error_5001"
        self.assertFalse(self.check(value, code=0)["all_checks_passed"])
    def test_json_parser_rejects_nonfinite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "payload.json"; path.write_text('{"value": NaN}\n', encoding="utf-8")
            with self.assertRaises(ValueError): read_json_payload(path)


if __name__ == "__main__": unittest.main()
