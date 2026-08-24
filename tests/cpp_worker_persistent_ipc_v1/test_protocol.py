from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    FrameError, HEADER, MESSAGE_SHUTDOWN, StepRequest, decode_response, encode_control,
    encode_request, validate_response,
)


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "build-release" / "cfd_ancf_cpp_worker.exe"


def request(index: int) -> StepRequest:
    return StepRequest(index, 559 + index, index, 2207500000 + index * 1250000,
                       2.2075 + index * 0.00125, 0.00125, 10000 + index, 20000 + index,
                       "cpp_worker_test_run", "cpp_worker_test_case", (1.0, 2.0), (0.1, 0.2), (0.0, 0.0))


class CppPersistentWorkerTests(unittest.TestCase):
    def test_release_worker_processes_forty_steps_with_one_pid(self):
        self.assertTrue(WORKER.is_file(), "Release worker must be built before this test")
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for index in range(1, 41):
                value = request(index)
                process.stdin.write(encode_request(value)); process.stdin.flush()
                header = process.stdout.read(HEADER.size)
                magic, length, message_type = HEADER.unpack(header)
                body = process.stdout.read(length)
                response = decode_response(header + body)
                validate_response(value, response)
                self.assertEqual(response.global_step, 559 + index)
                self.assertEqual(message_type, 2)
            self.assertIsNone(process.poll())
        finally:
            process.terminate(); process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def test_wrong_sequence_is_rejected_without_retry(self):
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            first = request(1); process.stdin.write(encode_request(first)); process.stdin.flush()
            header = process.stdout.read(HEADER.size); body = process.stdout.read(HEADER.unpack(header)[1])
            response = decode_response(header + body); validate_response(first, response)
            with self.assertRaises(FrameError):
                # Client-side monotonic guard is the fail-closed boundary.
                validate_response(request(3), response)
        finally:
            process.terminate(); process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def test_nan_request_fails_before_frame(self):
        with self.assertRaises(FrameError):
            encode_request(StepRequest(1, 560, 1, 2208750000, 2.20875, 0.00125, 1, 2,
                                       "r", "c", (float("nan"),), (0.0,), (0.0,)))

    def test_protocol_shutdown_exits_cleanly(self):
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.terminate(); process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_identity_mismatch_is_fail_closed(self):
        value = request(1)
        with self.assertRaises(FrameError):
            validate_response(value, type("Response", (), {
                "protocol_version": 1, "sequence": 1, "transaction_id": 2, "request_id": value.request_id, "ack": 1, "global_step": 560,
                "case_local_bridge_step": 1, "integer_tick": 2208750000,
                "time_s": 2.20875, "return_code": 0, "run_id": "wrong",
                "case_id": value.case_id, "payload_hash": b"",
            })())


if __name__ == "__main__":
    unittest.main()
