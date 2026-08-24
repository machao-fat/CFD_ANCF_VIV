from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.coupling.persistent_ancf import PersistentANCFRunner, PersistentRunnerError, StaleResponseError
from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run, probe_python_runtime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAKE_WORKER = Path(__file__).with_name("fake_worker.py")
CONFIG = {"nElem": 2, "dt": 0.0025}


class PersistentANCFLifecycleTests(unittest.TestCase):
    def make_runner(self, mode: str = "success", *, child: bool = True, timeout: float = 0.5):
        run = create_runtime_run(PROJECT_ROOT, "stage4e_b1_v3")
        command = [sys.executable, str(FAKE_WORKER), "--root", str(run), "--mode", mode]
        if child:
            command.append("--child")
        runner = PersistentANCFRunner(
            config=CONFIG,
            matlab_exe=sys.executable,
            request_dir=run,
            timeout_s=timeout,
            launch_command=command,
            process_environment=build_task_environment(run),
        )
        return run, runner

    def assert_closed(self, runner: PersistentANCFRunner) -> None:
        self.assertIsNone(runner.process)
        self.assertIsNone(runner.worker_pid)
        self.assertFalse(runner.alive)
        self.assertIsNone(runner._log_stream)
        self.assertEqual(runner.cleanup_audit["owned_pid_count_after"], 0)

    def test_success_shutdown_is_idempotent_and_closes_owned_tree(self):
        run, runner = self.make_runner()
        response = runner.start()
        self.assertEqual(response["status"], "complete")
        self.assertTrue(runner.alive)
        self.assertTrue(runner.owned_process_records)
        runner.shutdown()
        runner.shutdown()
        self.assert_closed(runner)
        self.assertTrue(run.drive.upper() == "D:")

    def test_initialize_immediate_exit_cleans_launcher_and_child(self):
        _run, runner = self.make_runner("exit")
        with self.assertRaises(PersistentRunnerError):
            runner.start()
        self.assert_closed(runner)

    def test_initialize_timeout_cleans_tree_and_does_not_restart(self):
        _run, runner = self.make_runner("timeout", timeout=0.1)
        with self.assertRaises(TimeoutError):
            runner.start()
        self.assert_closed(runner)
        with self.assertRaises(PersistentRunnerError):
            runner.start()

    def test_initialize_protocol_error_preserves_evidence_and_cleans(self):
        run, runner = self.make_runner("error")
        with self.assertRaises(PersistentRunnerError):
            runner.start()
        self.assert_closed(runner)
        self.assertTrue((run / "matlab_persistent_worker.log").is_file())
        self.assertTrue((run / "requests").is_dir())

    def test_unrelated_sentinel_survives_owned_cleanup(self):
        run, runner = self.make_runner(child=False)
        sentinel = subprocess.Popen([sys.executable, "-c", "import threading; threading.Event().wait(600)"])
        try:
            runner.start()
            runner.shutdown()
            self.assertIsNotNone(psutil_process(sentinel.pid))
        finally:
            if sentinel.poll() is None:
                sentinel.terminate()
                sentinel.wait(timeout=5)
        self.assertTrue(run.drive.upper() == "D:")

    def test_runtime_probe_and_worker_environment_are_on_d_drive(self):
        run, runner = self.make_runner(child=False)
        # The test process itself is not allowed to mutate global TEMP.  The
        # task-scoped child environment is the contract under test.
        self.assertTrue(run.drive.upper() == "D:")
        runner.start()
        runner.shutdown()
        env = json.loads((run / "environment_audit" / "fake_worker_environment.json").read_text(encoding="utf-8"))
        self.assertTrue(all(Path(value).drive.upper() == "D:" for value in env.values()))

    def test_exited_worker_shutdown_is_safe_and_creation_identity_is_recorded(self):
        _run, runner = self.make_runner(child=False)
        runner.start()
        records = runner.owned_process_records
        self.assertTrue(records)
        self.assertTrue(all(record["creation_time"] is not None for record in records))
        assert runner.process is not None
        runner.process.kill()
        runner.process.wait(timeout=5)
        runner.shutdown()
        self.assert_closed(runner)

    def test_failed_shutdown_keeps_request_and_log_evidence(self):
        run, runner = self.make_runner("timeout", timeout=0.1)
        with self.assertRaises(TimeoutError):
            runner.start()
        runner.shutdown()
        self.assertTrue((run / "requests").is_dir())
        self.assertTrue((run / "matlab_persistent_worker.log").is_file())

    def test_runner_does_not_touch_process_outside_its_registry(self):
        run, runner = self.make_runner(child=True)
        sentinel = subprocess.Popen([sys.executable, "-c", "import threading; threading.Event().wait(600)"])
        try:
            runner.start()
            owned = {record["pid"] for record in runner.owned_process_records}
            self.assertNotIn(sentinel.pid, owned)
            runner.shutdown()
            self.assertIsNotNone(psutil_process(sentinel.pid))
        finally:
            if sentinel.poll() is None:
                sentinel.terminate()
                sentinel.wait(timeout=5)

    def test_owned_registry_and_diagnostics_are_persisted(self):
        run, runner = self.make_runner(child=False)
        runner.start()
        runner.shutdown()
        registry = json.loads((run / "process_registry" / "owned_process_registry.json").read_text(encoding="utf-8"))
        diagnostics = json.loads((run / "process_registry" / "runner_diagnostics.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(registry["started_count"], 1)
        self.assertEqual(registry["task_owned_residual_process_count"], 0)
        self.assertTrue(registry["closed_pids"])
        self.assertTrue(any(event["status"] == "success" for event in diagnostics["events"]))

    def test_timeout_diagnostic_records_owned_pid_and_evidence_paths(self):
        run, runner = self.make_runner("timeout", timeout=0.1)
        with self.assertRaises(TimeoutError):
            runner.start()
        diagnostics = json.loads((run / "process_registry" / "runner_diagnostics.json").read_text(encoding="utf-8"))
        timeout_events = [event for event in diagnostics["events"] if event["status"] == "initialize_timeout"]
        self.assertTrue(timeout_events)
        self.assertEqual(timeout_events[-1]["request_dir"], str(run))
        self.assertTrue(timeout_events[-1]["log_path"].startswith(str(run)))
        runner.shutdown()

    def test_stale_response_is_rejected_before_launch(self):
        run, runner = self.make_runner(child=False)
        (run / "responses" / "response_stale.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(StaleResponseError):
            runner.start()
        self.assert_closed(runner)

    def test_keyboard_interrupt_cleans_owned_tree_and_propagates_original(self):
        _run, runner = self.make_runner(child=True)
        with patch.object(runner, "_call", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                runner.start()
        self.assert_closed(runner)
        with self.assertRaises(PersistentRunnerError):
            runner.start()

    def test_system_exit_cleans_owned_tree_and_propagates_original(self):
        _run, runner = self.make_runner(child=True)
        with patch.object(runner, "_call", side_effect=SystemExit(23)):
            with self.assertRaises(SystemExit) as context:
                runner.start()
        self.assertEqual(context.exception.code, 23)
        self.assert_closed(runner)
        with self.assertRaises(PersistentRunnerError):
            runner.start()

    def test_creation_time_mismatch_refuses_cleanup(self):
        _run, runner = self.make_runner(child=False)
        runner.start()
        records = runner.owned_process_records
        self.assertTrue(records)
        tampered = dict(records[0])
        tampered["creation_time"] = float(tampered["creation_time"]) + 123.0
        self.assertFalse(runner._safe_to_cleanup(tampered, {int(tampered["pid"])}))
        runner.shutdown()
        self.assert_closed(runner)


def psutil_process(pid: int):
    try:
        import psutil
        return psutil.Process(pid) if psutil.pid_exists(pid) else None
    except ImportError:
        return None


if __name__ == "__main__":
    unittest.main()
