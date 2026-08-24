from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.performance_instrumentation_matlab_worker_v1.protocol import ProtocolError, WorkerRequest
from coupling.performance_matlab_worker_bridge_v1.transport import FileWorkerTransport


class TransportTests(unittest.TestCase):
    def test_atomic_contract_and_request_identity(self):
        runtime = Path(tempfile.mkdtemp()) / "D_drive" / "performance_matlab_worker_bridge_v1"
        transport = FileWorkerTransport(runtime=runtime, run_id="run94", case_id="case94", timeout_s=.01)
        contract = transport.publish_contract()
        self.assertTrue(contract.is_file())
        request = WorkerRequest.create(operation="prediction", run_id="run94", case_id="case94", global_step=560,
                                       case_local_bridge_step=0, time_s=2.20875, integer_tick=2208750000,
                                       request_id="r560", transaction_id="t560", payload={"state": "path"})
        with self.assertRaises(ProtocolError):
            transport.send(request)
        self.assertTrue(transport.failed)

    def test_stop_is_explicit_and_no_retry(self):
        runtime = Path(tempfile.mkdtemp()) / "D_drive" / "performance_matlab_worker_bridge_v1"
        transport = FileWorkerTransport(runtime=runtime, run_id="run94", case_id="case94")
        transport.publish_contract(); stop = transport.stop()
        self.assertTrue(stop.is_file())
        with self.assertRaises(ProtocolError):
            transport.send(WorkerRequest.create(operation="prediction", run_id="run94", case_id="case94", global_step=560,
                                                case_local_bridge_step=0, time_s=2.20875, integer_tick=2208750000,
                                                request_id="r560", transaction_id="t560", payload={}))


if __name__ == "__main__":
    unittest.main()
