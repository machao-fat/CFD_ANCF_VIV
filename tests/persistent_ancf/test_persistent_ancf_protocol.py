from __future__ import annotations

import unittest
import os
from pathlib import Path

from src.coupling.persistent_ancf import PersistentANCFRunner, PersistentRunnerError, StaleResponseError, WorkerExitedError
from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run
from src.coupling.stage4e_b1_v3_1_2_closeout.real_runner import RealRunnerSession


MATLAB = Path(os.environ.get("CFD_ANCF_MATLAB_EXE", r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe"))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = {
    "L": 10.0, "D": 1.0, "dInner": 0.9, "nElem": 2, "nSlices": 3,
    "s_ref_m": [1.25, 5.0, 8.75], "topTension_N": 1.0e7,
    "youngs_modulus_Pa": 2.07e11, "dt": 0.0025, "start_time_s": 0.0,
    "newton_tolerance": 1.0e-8, "max_newton": 40,
}
ZERO_LOAD = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
TRANSVERSE_LOAD = [[0.0, 10.0, 0.0], [0.0, 10.0, 0.0], [0.0, 10.0, 0.0]]


class PersistentANCFProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(MATLAB.is_file(), f"MATLAB executable is not installed: {MATLAB}")
        self.session = RealRunnerSession(project_root=PROJECT_ROOT, config=CONFIG, matlab_exe=MATLAB, purpose="formal_protocol_test")
        self.root = self.session.root
        self.runner = self.session.runner
        self.addCleanup(self.session.close)
        self.session.start()

    def tearDown(self) -> None:
        self.session.close()

    def step_to(self, step: int, load=ZERO_LOAD) -> dict:
        t = (step + 1) * CONFIG["dt"]
        self.runner.predict(step, t, ZERO_LOAD)
        response, _ = self.runner.correct(step, t, load)
        checkpoint = self.root / f"step_{step:04d}.mat"
        prepared = self.runner.prepare_checkpoint(checkpoint)
        self.runner.finalize_commit(prepared["checkpoint_token"])
        return response

    def test_direct_state_and_transaction_semantics(self) -> None:
        initial = self.runner.state_view()
        predicted, _ = self.runner.predict(0, CONFIG["dt"], TRANSVERSE_LOAD)
        predicted_state = self.runner.state_view()
        self.assertEqual(len(predicted["q"]), 18)
        self.assertEqual(set(initial), {"q", "qdot", "qddot"})
        self.assertNotEqual(predicted_state["qddot"], initial["qddot"])
        with self.assertRaises(PersistentRunnerError):
            self.runner.predict(0, CONFIG["dt"], ZERO_LOAD)
        corrected, _ = self.runner.correct(0, CONFIG["dt"], ZERO_LOAD)
        self.assertIn("checkpoint_token", corrected)
        self.assertEqual(self.runner.heartbeat()["global_step"], -1)
        self.runner.discard_staged()
        self.assertEqual(self.runner.heartbeat()["global_step"], -1)
        self.step_to(0)
        self.assertEqual(self.runner.heartbeat()["global_step"], 0)
        self.assertEqual(self.runner.start_count, 1)

    def test_checkpoint_restart(self) -> None:
        self.step_to(0)
        checkpoint = self.root / "restart.mat"
        self.runner.save_checkpoint(checkpoint)
        before = self.runner.state_view()
        self.runner.load_checkpoint(checkpoint)
        after = self.runner.state_view()
        self.assertEqual(before, after)
        self.step_to(1)
        self.assertEqual(self.runner.heartbeat()["global_step"], 1)

    def test_duplicate_command_and_stale_response_are_rejected(self) -> None:
        first = self.runner._call("heartbeat", command_id="fixed_command", operation_id="fixed_operation")
        self.assertEqual(first["command_id"], "fixed_command")
        (self.runner.response_root / "response_fixed_command.json").unlink()
        duplicate = self.runner._call("heartbeat", command_id="fixed_command", operation_id="fixed_operation", raise_on_error=False)
        self.assertEqual(duplicate["error_code"], "duplicate_command_id")
        stale_path = self.runner.response_root / "response_stale_command.json"
        stale_path.write_text('{"command_id":"stale_command","operation_id":"old"}\n', encoding="utf-8")
        with self.assertRaises(StaleResponseError):
            self.runner._call("heartbeat", command_id="stale_command", operation_id="new")

    def test_worker_exit_is_detected_without_silent_restart(self) -> None:
        assert self.runner.process is not None
        self.runner.process.kill()
        self.runner.process.wait(timeout=10.0)
        with self.assertRaises(WorkerExitedError):
            self.runner.heartbeat()
        self.assertEqual(self.runner.start_count, 1)


if __name__ == "__main__":
    unittest.main()
