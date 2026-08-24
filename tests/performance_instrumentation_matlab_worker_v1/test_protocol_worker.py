from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.performance_instrumentation_matlab_worker_v1.protocol import ProtocolError
from coupling.performance_instrumentation_matlab_worker_v1.worker import OfflineMatlabWorker


class PersistentWorkerTests(unittest.TestCase):
    def make_worker(self, fault=None):
        return OfflineMatlabWorker(run_id="run93", case_id="case93", runtime=Path(tempfile.mkdtemp()), fault=fault)

    def test_one_worker_handles_full_segment_and_audits_metadata(self):
        worker = self.make_worker(); audit = worker.start()
        for step in range(40):
            response = worker.process(global_step=step, case_local_bridge_step=step, time_s=(step + 1) * .0025,
                                       integer_tick=(step + 1) * 2500000, request_id=f"r{step}", transaction_id=f"t{step}")
            self.assertEqual(response.worker_pid, audit.pid)
            self.assertEqual(response.worker_creation_time, audit.creation_time_ns)
            self.assertTrue(response.output_sha256)
            self.assertGreater(response.output_size, 0)
        self.assertEqual(worker.start_count if hasattr(worker, "start_count") else 1, 1)
        self.assertEqual(len(worker.responses), 40)
        self.assertEqual(worker.stop().cleanup_result, "closed")
        self.assertEqual(worker.residual, 0)

    def test_rejects_order_identity_and_metadata_faults(self):
        for fault in ("5001", "nonzero", "timeout", "disconnect", "crash", "missing_output", "nan",
                      "identity", "tick_mismatch", "time_mismatch", "hash_mismatch"):
            with self.subTest(fault=fault):
                worker = self.make_worker(fault); worker.start()
                with self.assertRaises(ProtocolError):
                    worker.process(global_step=0, case_local_bridge_step=0, time_s=.0025, integer_tick=2500000,
                                   request_id="r0", transaction_id="t0")
                worker.stop(return_code=1)

    def test_rejects_duplicate_stale_and_out_of_order_without_retry(self):
        worker = self.make_worker(); worker.start()
        worker.process(global_step=0, case_local_bridge_step=0, time_s=.0025, integer_tick=2500000,
                       request_id="r0", transaction_id="t0")
        for kwargs in (
            {"global_step": 0, "case_local_bridge_step": 0, "request_id": "r0", "transaction_id": "t0"},
            {"global_step": 2, "case_local_bridge_step": 2, "request_id": "r2", "transaction_id": "t2"},
            {"global_step": 1, "case_local_bridge_step": 2, "request_id": "r1", "transaction_id": "t1"},
        ):
            with self.assertRaises(ProtocolError):
                worker.process(time_s=.005, integer_tick=5000000, **kwargs)
        worker.stop(return_code=1)

    def test_initialize_is_explicit_and_time_tick_mismatch_is_rejected(self):
        worker = self.make_worker(); worker.start()
        init = worker.initialize(global_step=0, case_local_bridge_step=0, time_s=.0025,
                                 integer_tick=2500000, request_id="init", transaction_id="init-t")
        self.assertEqual(init.operation, "initialize")
        with self.assertRaises(ProtocolError):
            worker.process(global_step=0, case_local_bridge_step=0, time_s=.0025, integer_tick=2500001,
                           request_id="r0", transaction_id="t0")
        worker.stop(return_code=1)


if __name__ == "__main__":
    unittest.main()
