import tempfile
import threading
import time
import json
import unittest
from pathlib import Path

from src.coupling.performance_optimization_v1.contracts import OptimizationConfig
from src.coupling.performance_optimization_v1.scheduler import BarrierError, GlobalBarrierScheduler
from src.coupling.performance_optimization_v1.workers import MockMatlabWorker, MockOpenFOAMSlice, WorkerLifecycleError


class WorkerSchedulerTests(unittest.TestCase):
    def test_matlab_and_openfoam_start_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            matlab = MockMatlabWorker(run_id="r", case_id="c", output_dir=Path(tmp) / "m")
            matlab.start()
            for step in range(3):
                envelope = matlab.process_step(global_step=step, case_local_bridge_step=step, time_s=step * .0025, integer_tick=step)
                self.assertEqual(envelope.output_hash, envelope.payload_hash)
                self.assertGreater(envelope.size, 0)
            self.assertEqual(len(matlab.request_audits), 3)
            required = {"run_id", "case_id", "global_step", "case_local_bridge_step", "time_s",
                        "integer_tick", "request_id", "transaction_id", "payload_hash", "output_hash",
                        "size", "mtime_ns", "return_code", "finite_audit", "worker_pid"}
            self.assertTrue(required.issubset(matlab.request_audits[0]))
            self.assertTrue(required.issubset(matlab.response_audits[0]))
            response_path = Path(tmp) / "m" / "response_000002.json"
            response_json = json.loads(response_path.read_text(encoding="utf-8"))
            self.assertEqual(response_json["size"], response_path.stat().st_size)
            self.assertEqual(response_json["mtime_ns"], response_path.stat().st_mtime_ns)
            self.assertEqual(matlab.start_count, 1)
            matlab.stop()
            with self.assertRaises(WorkerLifecycleError):
                matlab.process_step(global_step=3, case_local_bridge_step=3, time_s=.0075, integer_tick=3)

    def test_parallel_three_slice_global_barrier(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = []
            scheduler = GlobalBarrierScheduler(config=OptimizationConfig(), run_id="r", case_id="c",
                runtime_dir=tmp, persistent_matlab=True, persistent_openfoam=True,
                parallel_slices=True, persistent_ipc=True,
                checkpoint_callback=lambda step, result: seen.append((step, len(result))))
            result = scheduler.run(steps=4)
            self.assertEqual(len(result.records), 4)
            self.assertEqual(seen, [(0, 3), (1, 3), (2, 3), (3, 3)])
            self.assertEqual(result.matlab_start_count, 1)
            self.assertEqual(result.openfoam_start_counts, {0: 1, 1: 1, 2: 1})
            self.assertTrue(all(record.barrier_passed for record in result.records))
            self.assertEqual(result.owned_residual, 0)
            self.assertEqual(len(result.worker_exchanges["matlab"]["requests"]), 4)
            self.assertEqual(len(result.worker_exchanges["slices"]["0"]["responses"]), 4)

    def test_fault_is_fail_closed_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = GlobalBarrierScheduler(config=OptimizationConfig(), run_id="r", case_id="c",
                runtime_dir=tmp, faults={1: "nonzero"})
            with self.assertRaises(BarrierError):
                scheduler.run(steps=2)

    def test_missing_output_and_identity_faults_fail_closed(self):
        for fault in ("missing_output", "identity", "tick_mismatch", "time_mismatch", "nan", "5001"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                scheduler = GlobalBarrierScheduler(config=OptimizationConfig(), run_id="r", case_id="c",
                    runtime_dir=tmp, faults={-1: fault})
                with self.assertRaises(BarrierError):
                    scheduler.run(steps=1)

    def test_slice_work_overlaps_but_checkpoint_waits_for_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = threading.Lock()
            active = {"now": 0, "max": 0}
            checkpoint_active = []

            def compute(slice_id, step, time_s):
                with lock:
                    active["now"] += 1
                    active["max"] = max(active["max"], active["now"])
                time.sleep(0.01)
                with lock:
                    active["now"] -= 1
                return {"force_y_N": float(slice_id + step)}

            scheduler = GlobalBarrierScheduler(config=OptimizationConfig(), run_id="r", case_id="c",
                runtime_dir=tmp, persistent_matlab=True, persistent_openfoam=True,
                parallel_slices=True, persistent_ipc=False, slice_compute=compute,
                checkpoint_callback=lambda step, result: checkpoint_active.append(active["now"]))
            result = scheduler.run(steps=2)
            self.assertGreaterEqual(active["max"], 2)
            self.assertEqual(checkpoint_active, [0, 0])
            self.assertTrue(all(record.barrier_passed and record.checkpoint_committed for record in result.records))
