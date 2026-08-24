import unittest

from src.coupling.stage4f_three_slice_short_window_v1_repair3.process_evidence import (
    audit_process_registry, ownership_matches, validate_process_record,
)


def record():
    return {"pid": 123, "creation_time": 10.5, "parent_pid": 10, "executable": "wsl.exe",
            "command_line": ["wsl.exe", "pimpleFoam"], "cwd": "D:/runtime", "start_timestamp": "start",
            "end_timestamp": "end", "return_code": 0, "log_path": "D:/runtime/log", "shutdown_method": "natural_exit",
            "ownership_basis": "Popen pid plus observed creation time"}


class TestProcessEvidence(unittest.TestCase):
    def test_complete_record(self):
        self.assertTrue(validate_process_record(record())["passed"])

    def test_missing_command_rejected(self):
        row = record(); del row["command_line"]
        self.assertFalse(validate_process_record(row)["passed"])

    def test_missing_cwd_rejected(self):
        row = record(); del row["cwd"]
        self.assertFalse(audit_process_registry([row])["command_cwd_complete"])

    def test_creation_time_binds_ownership(self):
        row = record()
        self.assertTrue(ownership_matches(row, pid=123, creation_time=10.5))
        self.assertFalse(ownership_matches(row, pid=123, creation_time=11.0))

    def test_duplicate_identity_rejected(self):
        self.assertFalse(audit_process_registry([record(), record()])["passed"])


if __name__ == "__main__":
    unittest.main()
