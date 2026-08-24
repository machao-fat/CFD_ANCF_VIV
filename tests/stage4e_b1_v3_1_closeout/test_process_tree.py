from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run
from src.coupling.stage4e_b1_v3_1_closeout.evidence import EventLog, ProcessEvidence, validate_event_log


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).with_name("fake_tree.py")


def make_tree(*, launcher_exits: bool = False) -> tuple[Path, str, EventLog, ProcessEvidence, subprocess.Popen[str]]:
    run = create_runtime_run(PROJECT_ROOT, "stage4e_b1_v3_1", run_id=f"fake_{os.getpid()}_{time.time_ns()}")
    token = f"fake_{os.getpid()}_{time.time_ns()}"
    log = EventLog(run / "logs" / "raw_event_log.jsonl", run_id=run.name, run_token=token)
    evidence = ProcessEvidence(log, run_dir=run, run_token=token)
    command = [sys.executable, str(FAKE), "--token", token]
    if launcher_exits:
        command.append("--launcher-exits")
    process = subprocess.Popen(command, cwd=str(run), env=build_task_environment(run))
    evidence.register_pid(process.pid, purpose="fake_launcher", log_path=run / "logs" / "fake.log")
    evidence.start()
    return run, token, log, evidence, process


def stop_tree(evidence: ProcessEvidence, process: subprocess.Popen[str]) -> list[dict]:
    try:
        evidence.scan_once()
        evidence.stop()
        actions = evidence.cleanup(timeout_s=3.0)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        return actions
    finally:
        evidence.stop()


class ProcessTreeEvidenceTests(unittest.TestCase):
    def test_launcher_child_grandchild_are_observed(self):
        run, _token, log, evidence, process = make_tree()
        time.sleep(0.25)
        actions = stop_tree(evidence, process)
        self.assertTrue(any(row["purpose"] == "fake_launcher" for row in evidence.records.values()))
        self.assertGreaterEqual(len(evidence.records), 3)
        self.assertTrue(validate_event_log(log.path)["status"] == "passed")

    def test_launcher_exit_does_not_end_child_observation(self):
        run, _token, log, evidence, process = make_tree(launcher_exits=True)
        process.wait(timeout=5)
        time.sleep(0.25)
        actions = evidence.cleanup(timeout_s=3.0)
        evidence.stop()
        self.assertGreaterEqual(len(evidence.records), 3)
        self.assertTrue(any(item["action"] in {"terminate", "already_gone"} for item in actions))

    def test_creation_time_mismatch_refused(self):
        _run, _token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        row = next(iter(evidence.records.values()))
        tampered = dict(row, creation_time=float(row["creation_time"]) + 99.0)
        allowed, reason = evidence.safe_to_cleanup(tampered, owned_pids={int(row["pid"])} )
        stop_tree(evidence, process)
        self.assertFalse(allowed)
        self.assertIn("creation", reason)

    def test_cleanup_classifies_already_exited(self):
        _run, _token, _log, evidence, process = make_tree()
        process.terminate()
        process.wait(timeout=5)
        time.sleep(0.15)
        actions = evidence.cleanup(timeout_s=1.0)
        evidence.stop()
        self.assertTrue(any(item["action"] == "already_exited" for item in actions))

    def test_cleanup_classifies_identity_mismatch(self):
        _run, _token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        row = next(iter(evidence.records.values()))
        tampered = dict(row, creation_time=float(row["creation_time"]) + 123.0)
        allowed, reason = evidence.safe_to_cleanup(tampered, owned_pids={int(row["pid"])} )
        stop_tree(evidence, process)
        self.assertFalse(allowed)
        self.assertEqual(reason, "creation_time_mismatch")

    def test_initial_parent_mismatch_refused(self):
        _run, _token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        row = next(iter(evidence.records.values()))
        tampered = dict(row, parent_pid=int(row["parent_pid"]) + 1, command_line=[])
        allowed, reason = evidence.safe_to_cleanup(tampered, owned_pids=set())
        stop_tree(evidence, process)
        self.assertFalse(allowed)
        self.assertIn("parent", reason)

    def test_same_name_different_token_is_not_owned(self):
        run, token, log, evidence, process = make_tree()
        other = subprocess.Popen([sys.executable, str(FAKE), "--token", token + "_other"], cwd=str(run), env=build_task_environment(run))
        try:
            time.sleep(0.2)
            owned = {int(row["pid"]) for row in evidence.records.values()}
            self.assertNotIn(other.pid, owned)
        finally:
            stop_tree(evidence, process)
            if other.poll() is None:
                other.terminate()
            other.wait(timeout=5)

    def test_same_cwd_different_creation_time_refused(self):
        _run, _token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        row = next(iter(evidence.records.values()))
        allowed, reason = evidence.safe_to_cleanup(dict(row, creation_time=float(row["creation_time"]) + 1), owned_pids={int(row["pid"])} )
        stop_tree(evidence, process)
        self.assertFalse(allowed)
        self.assertIn("creation", reason)

    def test_timeout_cleanup_closes_owned_tree(self):
        _run, _token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        actions = stop_tree(evidence, process)
        self.assertTrue(actions)
        self.assertFalse(any(psutil_pid_exists(int(row["pid"])) for row in evidence.records.values()))

    def test_non_owned_process_is_not_terminated(self):
        run, _token, _log, evidence, process = make_tree()
        unrelated = subprocess.Popen([sys.executable, "-c", "import threading; threading.Event().wait(600)"], cwd=str(run))
        time.sleep(0.15)
        stop_tree(evidence, process)
        self.assertTrue(psutil_pid_exists(unrelated.pid))
        unrelated.terminate(); unrelated.wait(timeout=5)

    def test_event_sequence_is_continuous(self):
        _run, _token, log, evidence, process = make_tree()
        time.sleep(0.15)
        stop_tree(evidence, process)
        audit = validate_event_log(log.path)
        self.assertTrue(audit["sequence_continuous"])

    def test_required_event_fields_are_present(self):
        _run, _token, log, evidence, process = make_tree()
        time.sleep(0.15)
        stop_tree(evidence, process)
        rows = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(key in rows[0] for key in EventLog.REQUIRED))

    def test_event_log_flushes_each_event(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as temp:
            path = Path(temp) / "events.jsonl"
            log = EventLog(path, run_id="run", run_token="token")
            log.append("marker", payload={"x": 1})
            self.assertTrue(path.is_file())
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_event_log_tamper_is_detectable(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as temp:
            path = Path(temp) / "events.jsonl"
            log = EventLog(path, run_id="run", run_token="token")
            log.append("marker", payload={"x": 1})
            original = log.sha256()
            path.write_text(path.read_text(encoding="utf-8").replace('"x":1', '"x":2'), encoding="utf-8")
            self.assertNotEqual(original, log.sha256())

    def test_cleanup_is_idempotent_after_process_gone(self):
        _run, _token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        stop_tree(evidence, process)
        actions = evidence.cleanup(timeout_s=1.0)
        self.assertEqual(actions, [])

    def test_run_token_is_in_owned_command_line(self):
        _run, token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        rows = evidence.snapshot_records()
        stop_tree(evidence, process)
        self.assertTrue(any(token in " ".join(row["command_line"]) for row in rows))

    def test_cwd_is_recorded_for_owned_process(self):
        run, _token, _log, evidence, process = make_tree()
        time.sleep(0.15)
        rows = evidence.snapshot_records()
        stop_tree(evidence, process)
        self.assertTrue(any(str(run) == row["cwd"] for row in rows))

    def test_cleanup_actions_are_event_logged(self):
        _run, _token, log, evidence, process = make_tree()
        time.sleep(0.15)
        stop_tree(evidence, process)
        rows = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(row["event_type"] == "cleanup_action" for row in rows))

    def test_invalid_event_sequence_fails_validation(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as temp:
            path = Path(temp) / "events.jsonl"
            log = EventLog(path, run_id="run", run_token="token")
            log.append("marker")
            row = json.loads(path.read_text(encoding="utf-8"))
            row["sequence"] = 4
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(validate_event_log(path)["status"], "failed")


def psutil_pid_exists(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        return False


if __name__ == "__main__":
    unittest.main()
