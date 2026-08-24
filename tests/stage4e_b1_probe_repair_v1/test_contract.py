from __future__ import annotations

import unittest
from pathlib import Path

from src.coupling.stage4e_b1_probe_repair_v1.contract import SCHEMA, read_json_payload, validate_payload

RUNTIME = Path(r"D:\probe-repair-runtime\run")
TOKEN = "token"
RUN_ID = "run"


def payload() -> dict:
    root = str(RUNTIME).replace("\\", "/")
    return {
        "schema_version": SCHEMA, "run_id": RUN_ID, "run_token": TOKEN,
        "probe_begin": True, "probe_end": True, "version": "9.11.0.2911900 (R2021b) Update 8",
        "release": "2021b", "architecture": "win64", "license_test_matlab": 1,
        "TEMP": root + "/tmp", "TMP": root + "/tmp", "TMPDIR": root + "/tmp",
        "tempdir": root + "/tmp", "prefdir": root + "/matlab_pref", "pwd": root,
        "application_service": "ok",
    }


class ProbeContractTests(unittest.TestCase):
    def valid(self, value=None, code=0):
        return validate_payload(value or payload(), runtime_root=RUNTIME, return_code=code, run_id=RUN_ID, run_token=TOKEN,
            executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")

    def test_valid_release_license_architecture(self):
        self.assertTrue(self.valid()["all_checks_passed"])

    def test_missing_field_fails(self):
        value = payload(); del value["release"]
        self.assertFalse(self.valid(value)["all_checks_passed"])

    def test_wrong_variable_name_fails(self):
        value = payload(); value["release_R2021b"] = value.pop("release")
        self.assertFalse(self.valid(value)["all_checks_passed"])

    def test_display_release_is_not_native_release(self):
        value = payload(); value["release"] = "R2021b"
        self.assertFalse(self.valid(value)["all_checks_passed"])

    def test_nonzero_return_code_fails(self):
        self.assertFalse(self.valid(code=1)["all_checks_passed"])

    def test_nan_and_infinity_are_rejected(self):
        value = payload(); value["diagnostic"] = float("nan")
        self.assertFalse(self.valid(value)["all_checks_passed"])
        value = payload(); value["diagnostic"] = float("inf")
        self.assertFalse(self.valid(value)["all_checks_passed"])

    def test_c_drive_temp_tmp_prefdir_fail(self):
        for key in ("TEMP", "TMP", "TMPDIR", "tempdir", "prefdir"):
            value = payload(); value[key] = r"C:\Users\Administrator\AppData\Local\Temp\probe"
            self.assertFalse(self.valid(value)["all_checks_passed"], key)

    def test_wrong_architecture_or_license_fails(self):
        value = payload(); value["architecture"] = "maci64"
        self.assertFalse(self.valid(value)["all_checks_passed"])
        value = payload(); value["license_test_matlab"] = 0
        self.assertFalse(self.valid(value)["all_checks_passed"])

    def test_json_parser_rejects_nonfinite_constants(self):
        path = Path(__file__).with_name("_nonfinite_probe_fixture.json")
        path.write_text('{"value": NaN}\n', encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                read_json_payload(path)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
