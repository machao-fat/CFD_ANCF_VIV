from __future__ import annotations

import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    FrameError, HEADER, MESSAGE_SHUTDOWN, StepRequest, decode_response, encode_control,
    encode_request, validate_response,
)

WORKER = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "build-release" / "Release" / "cfd_ancf_cpp_worker.exe"


def request(index: int, *, request_id: int | None = None, transaction_id: int | None = None) -> StepRequest:
    return StepRequest(index, 559 + index, index, 2207500000 + index * 1250000,
                       2.2075 + index * 0.00125, 0.00125,
                       request_id if request_id is not None else 100000 + index,
                       transaction_id if transaction_id is not None else 200000 + index,
                       "stage153_transport_run", "stage153_transport_case",
                       (1.0, 2.0), (0.1, 0.2), (0.0, 0.0))


class TransportWorkerHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not WORKER.is_file():
            raise unittest.SkipTest("Stage 153 Release transport worker has not been built")

    def test_duplicate_request_id_is_rejected_by_direct_worker(self) -> None:
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None and process.stdout is not None
        try:
            first = request(1)
            process.stdin.write(encode_request(first)); process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            body = process.stdout.read(HEADER.unpack(header)[1])
            validate_response(first, decode_response(header + body))
            duplicate = request(2, request_id=first.request_id)
            process.stdin.write(encode_request(duplicate)); process.stdin.flush()
            process.stdin.close(); process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_time_tick_mismatch_is_rejected_before_frame(self) -> None:
        bad = replace(request(2), integer_tick=2209000000)
        with self.assertRaises(FrameError):
            encode_request(bad)


if __name__ == "__main__":
    unittest.main()
