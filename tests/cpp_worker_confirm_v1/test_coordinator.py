from __future__ import annotations

import json
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from coupling.cpp_worker_confirm_v1.coordinator import ConfirmError, KernelWorker, Mapping, MockSlice, _fixture, run_mock_confirm
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest


class CppConfirmTests(unittest.TestCase):
    def test_mapping_is_explicit_for_source_559_to_560(self) -> None:
        bridge, time_s, tick = Mapping().identity(560)
        self.assertEqual((bridge, tick), (1, 2_208_750_000))
        self.assertAlmostEqual(time_s, 2.20875)

    def test_confirm_is_exactly_bounded_to_forty_steps(self) -> None:
        with self.assertRaises(ConfirmError):
            run_mock_confirm(runtime=Path(tempfile.mkdtemp()), steps=39)

    def test_slice_rejects_stale_time_and_tick(self) -> None:
        item = MockSlice(0, Mapping()); item.start()
        with self.assertRaises(ConfirmError):
            item.advance(global_step=560, time_s=2.2075, tick=2_207_500_000, q=(0.0, 0.0, 0.0, 0.0))
        item.stop()

    def test_slice_rejects_duplicate_lifecycle_start(self) -> None:
        item = MockSlice(1, Mapping()); item.start()
        with self.assertRaises(ConfirmError):
            item.start()

    def test_worker_response_timeout_fails_closed(self) -> None:
        class BlockingStream:
            def __init__(self):
                self.release = threading.Event()

            def write(self, _value):
                return None

            def flush(self):
                return None

            def read(self, _size):
                self.release.wait(1.0)
                return b""

            def close(self):
                self.release.set()

        stream = BlockingStream()
        fake_process = SimpleNamespace(stdin=stream, stdout=stream, pid=12345)
        worker = KernelWorker(Path(__file__), Path(tempfile.mkdtemp()), "run", "case", timeout_s=0.01)
        worker.process = fake_process
        model, q, qdot, qddot, base_load = _fixture()
        request = KernelStepRequest(
            sequence=1, global_step=560, case_local_bridge_step=1,
            integer_tick=2_208_750_000, time_s=2.20875, dt_s=0.00125,
            request_id=1, transaction_id=2, run_id="run", case_id="case",
            model=model, q=q, qdot=qdot, qddot=qddot, base_load=base_load,
            slice_force=(0.0,) * (3 * model.slices),
        )
        with self.assertRaises(ConfirmError):
            worker.step(request)
        self.assertEqual(worker.audit["failure_classification"], "worker_timeout")
        stream.release.set()

    def test_mock_confirm_has_one_worker_and_three_slice_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            gate = run_mock_confirm(runtime=runtime, results_dir=runtime / "evidence")
            self.assertTrue(gate["gate"].endswith("pass"))
            self.assertEqual(gate["physical_committed"], 40)
            self.assertEqual(gate["fully_audited"], 40)
            self.assertEqual(gate["worker_start_count"], 1)
            self.assertEqual(gate["slice_start_counts"], [1, 1, 1])
            self.assertEqual(gate["owned_residual"], 0)
            result = json.loads((runtime / "evidence" / "mock_confirm_result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["step_records"][0]["global_step"], 560)
            self.assertEqual(result["step_records"][-1]["global_step"], 599)
            self.assertEqual(result["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})


if __name__ == "__main__":
    unittest.main()
