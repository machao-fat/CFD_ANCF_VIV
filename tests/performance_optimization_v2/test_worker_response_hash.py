from __future__ import annotations

import hashlib
import json
import unittest

from coupling.performance_instrumentation_matlab_worker_v1.protocol import WorkerRequest, WorkerResponse
from coupling.performance_matlab_worker_bridge_v1.transport import FileWorkerTransport


class WorkerResponseHashTests(unittest.TestCase):
    def test_matlab_serialized_payload_hash_is_verified_without_python_reformatting(self):
        payload_text = '{"state_view":{"q":[7.3651250224083482E-5]},"time_s":2.2075}'
        request = WorkerRequest.create(operation="initialize", run_id="r", case_id="c", global_step=559,
            case_local_bridge_step=0, time_s=2.2075, integer_tick=2207500000,
            request_id="req", transaction_id="tx", payload={"x": 1})
        response_data = {
            "schema_version": request.schema_version, "formal_protocol_version": request.formal_protocol_version,
            "operation": request.operation, "run_id": request.run_id, "case_id": request.case_id,
            "global_step": request.global_step, "case_local_bridge_step": request.case_local_bridge_step,
            "time_s": request.time_s, "integer_tick": request.integer_tick, "request_id": request.request_id,
            "transaction_id": request.transaction_id, "payload_hash": request.payload_hash,
            "output_sha256": hashlib.sha256((payload_text + "\n").encode("utf-8")).hexdigest(),
            "output_size": len((payload_text + "\n").encode("utf-8")), "output_mtime_ns": 1,
            "return_code": 0, "finite_value_audit": {"finite": True}, "worker_pid": 1,
            "worker_creation_time": 1, "parent_pid": 1, "command_line": [],
            "payload": {"state_view": {"q": [7.3651250224083482e-5]}, "time_s": 2.2075},
        }
        envelope = json.dumps({**response_data, "payload": None}, ensure_ascii=True, separators=(",", ":"))
        raw_response = envelope.replace('"payload":null', '"payload":' + payload_text)
        raw_hash = FileWorkerTransport._raw_payload_hash(raw_response)
        response = WorkerResponse(**json.loads(raw_response))
        response.validate(request, raw_payload_sha256=raw_hash)


if __name__ == "__main__":
    unittest.main()
