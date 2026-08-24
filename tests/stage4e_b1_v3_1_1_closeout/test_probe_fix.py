from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.coupling.persistent_ancf import PersistentANCFRunner
from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run
from src.coupling.stage4e_b1_v3_1_closeout.evidence import EventLog, ProcessEvidence, validate_event_log
from src.coupling.stage4e_b1_v3_1_1_closeout.probe import (
    MATLAB_EXE,
    OLD_MATLAB_EXE,
    SCHEMA,
    _servicehost_classification,
    _validate_payload,
)


ROOT = Path(__file__).resolve().parents[2]
NEW_DEFAULT = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
TEST_RUNTIME = create_runtime_run(ROOT, "stage4e_b1_v3_1_1", run_id=f"test_{os.getpid()}_{time.time_ns()}")


def temp_dir():
    return tempfile.TemporaryDirectory(dir=str(TEST_RUNTIME / "tmp"))


def valid_payload(run: Path, run_id: str = "run", token: str = "token") -> dict:
    return {
        "schema_version": SCHEMA,
        "run_id": run_id,
        "run_token": token,
        "probe_begin": True,
        "version": "9.11.0.2911900 (R2021b)",
        "release": "R2021b",
        "architecture": "win64",
        "license_test_matlab": 1,
        "tempdir": str(run / "tmp"),
        "prefdir": str(run / "matlab_pref"),
        "pwd": str(run),
        "probe_end": True,
    }


class ProbeFixTests(unittest.TestCase):
    def test_matlab_and_launcher_logs_are_distinct(self):
        run = Path(r"D:\stage4e_b1_v3_1_1_test")
        internal = run / "logs" / "matlab_internal.log"
        console = run / "logs" / "launcher_console.log"
        self.assertNotEqual(internal.resolve(), console.resolve())
        self.assertEqual(MATLAB_EXE.name.lower(), "matlab.exe")

    def test_probe_payload_is_independent_from_console_text(self):
        with temp_dir() as temp:
            run = Path(temp).resolve()
            (run / "tmp").mkdir()
            (run / "matlab_pref").mkdir()
            payload_path = run / "probe_payload.json"
            payload_path.write_text(json.dumps(valid_payload(run)), encoding="utf-8")
            (run / "launcher_console.log").write_bytes(b"9.9.11... 202202win6wi corrupted\x80")
            result = _validate_payload(payload_path, run=run, run_id="run", token="token", return_code=0)
            self.assertTrue(result["all_checks_passed"])

    def test_malformed_console_does_not_affect_payload(self):
        with temp_dir() as temp:
            run = Path(temp).resolve()
            for name in ("tmp", "matlab_pref"):
                (run / name).mkdir()
            payload = run / "probe_payload.json"
            payload.write_text(json.dumps(valid_payload(run)), encoding="utf-8")
            (run / "launcher_console.log").write_bytes(b"\xff\xfe9.12\x00")
            self.assertTrue(_validate_payload(payload, run=run, run_id="run", token="token", return_code=0)["all_checks_passed"])

    def _validate_variant(self, **changes):
        with temp_dir() as temp:
            run = Path(temp).resolve()
            for name in ("tmp", "matlab_pref"):
                (run / name).mkdir()
            value = valid_payload(run)
            value.update(changes)
            path = run / "probe_payload.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return _validate_payload(path, run=run, run_id="run", token="token", return_code=0)

    def test_version_9_11_passes(self):
        self.assertTrue(self._validate_variant()["checks"]["version_9_11_series"])

    def test_version_9_9_rejected(self):
        self.assertFalse(self._validate_variant(version="9.9.0")["all_checks_passed"])

    def test_version_9_12_rejected(self):
        self.assertFalse(self._validate_variant(version="9.12.0")["all_checks_passed"])

    def test_release_rejected(self):
        self.assertFalse(self._validate_variant(release="R2022a")["all_checks_passed"])

    def test_architecture_rejected(self):
        self.assertFalse(self._validate_variant(architecture="glnxa64")["all_checks_passed"])

    def test_license_zero_rejected(self):
        self.assertFalse(self._validate_variant(license_test_matlab=0)["all_checks_passed"])

    def test_tempdir_escape_rejected(self):
        self.assertFalse(self._validate_variant(tempdir=r"D:\other\tmp")["all_checks_passed"])

    def test_prefdir_escape_rejected(self):
        self.assertFalse(self._validate_variant(prefdir=r"D:\other\pref")["all_checks_passed"])

    def test_run_token_mismatch_rejected(self):
        with temp_dir() as temp:
            run = Path(temp).resolve()
            (run / "tmp").mkdir(); (run / "matlab_pref").mkdir()
            path = run / "probe_payload.json"
            path.write_text(json.dumps(valid_payload(run, token="wrong")), encoding="utf-8")
            result = _validate_payload(path, run=run, run_id="run", token="token", return_code=0)
            self.assertFalse(result["checks"]["run_token"])

    def test_probe_end_missing_rejected(self):
        self.assertFalse(self._validate_variant(probe_end=False)["all_checks_passed"])

    def test_nonzero_launcher_rejected(self):
        with temp_dir() as temp:
            run = Path(temp).resolve(); (run / "tmp").mkdir(); (run / "matlab_pref").mkdir()
            path = run / "probe_payload.json"; path.write_text(json.dumps(valid_payload(run)), encoding="utf-8")
            result = _validate_payload(path, run=run, run_id="run", token="token", return_code=1)
            self.assertFalse(result["all_checks_passed"])

    def test_payload_schema_and_utf8_are_checked(self):
        with temp_dir() as temp:
            run = Path(temp).resolve(); (run / "tmp").mkdir(); (run / "matlab_pref").mkdir()
            path = run / "probe_payload.json"; path.write_bytes(b"{\xff")
            result = _validate_payload(path, run=run, run_id="run", token="token", return_code=0)
            self.assertFalse(result["checks"]["payload_utf8_json"])

    def test_service_mode_is_read_only_infrastructure(self):
        rows = [{"pid": 12, "creation_time": 1.0, "name": "MathWorksServiceHost.exe", "executable": "MathWorksServiceHost.exe", "command_line": ["MathWorksServiceHost.exe", "service"], "cwd": r"C:\Program Files"}]
        audit = _servicehost_classification(before=rows, runtime=Path(r"D:\runtime\run"), token="token")
        self.assertEqual(audit["preexisting_infrastructure_count"], 1)
        self.assertFalse(audit["rows"][0]["termination_requested"])

    def test_client_servicehost_is_not_preexisting_infrastructure(self):
        rows = [{"pid": 12, "creation_time": 1.0, "name": "MathWorksServiceHost.exe", "executable": "MathWorksServiceHost.exe", "command_line": ["MathWorksServiceHost.exe", "client-v1", "token"], "cwd": r"D:\runtime\run"}]
        audit = _servicehost_classification(before=rows, runtime=Path(r"D:\runtime\run"), token="token", records=[{"pid": 12}])
        self.assertEqual(audit["preexisting_infrastructure_count"], 0)

    def test_environment_value_points_to_new_launcher(self):
        env = build_task_environment(Path(r"D:\runtime\run"), {"CFD_ANCF_MATLAB_EXE": str(NEW_DEFAULT)})
        self.assertEqual(Path(env["CFD_ANCF_MATLAB_EXE"]).resolve(), NEW_DEFAULT.resolve())

    def test_new_launcher_exists_and_old_path_is_absent(self):
        self.assertTrue(NEW_DEFAULT.is_file())
        self.assertFalse(Path(r"D:\Matlab\bin\matlab.exe").exists())
        self.assertEqual(OLD_MATLAB_EXE, Path(r"D:\Matlab\bin\matlab.exe"))

    def test_runner_uses_environment_value(self):
        with patch.dict(os.environ, {"CFD_ANCF_MATLAB_EXE": str(NEW_DEFAULT)}):
            run = create_runtime_run(ROOT, "stage4e_b1_v3_1_1", run_id=f"runner_env_{os.getpid()}_{time.time_ns()}")
            runner = PersistentANCFRunner(config={"nElem": 2}, request_dir=run)
            self.assertEqual(runner.matlab_exe.resolve(), NEW_DEFAULT.resolve())

    def test_runner_uses_new_default_without_environment(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CFD_ANCF_MATLAB_EXE", None)
            run = create_runtime_run(ROOT, "stage4e_b1_v3_1_1", run_id=f"runner_default_{os.getpid()}_{time.time_ns()}")
            runner = PersistentANCFRunner(config={"nElem": 2}, request_dir=run)
            self.assertEqual(runner.matlab_exe.resolve(), NEW_DEFAULT.resolve())

    def test_explicit_runner_path_overrides_environment(self):
        with patch.dict(os.environ, {"CFD_ANCF_MATLAB_EXE": r"D:\wrong.exe"}):
            run = create_runtime_run(ROOT, "stage4e_b1_v3_1_1", run_id=f"runner_explicit_{os.getpid()}_{time.time_ns()}")
            runner = PersistentANCFRunner(config={"nElem": 2}, request_dir=run, matlab_exe=NEW_DEFAULT)
            self.assertEqual(runner.matlab_exe.resolve(), NEW_DEFAULT.resolve())

    def test_event_sequence_and_hash_are_valid(self):
        with temp_dir() as temp:
            path = Path(temp) / "events.jsonl"
            log = EventLog(path, run_id="run", run_token="token")
            log.append("marker")
            self.assertEqual(validate_event_log(path)["status"], "passed")
            self.assertEqual(validate_event_log(path)["sha256"], log.sha256())


if __name__ == "__main__":
    unittest.main()
