from __future__ import annotations

import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
import os
import sys

os.environ.setdefault("CFD_ANCF_OFFLINE_LEGACY_TRANSPORT", "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    FrameError, HEADER, MESSAGE_SHUTDOWN, REQUEST, StepRequest, decode_response, encode_control,
    encode_request, validate_response,
)

_BUILD_ROOT = Path(os.environ.get(
    "CFD_ANCF_STAGE_BUILD",
    str(ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "build-release"),
))
WORKER = _BUILD_ROOT / "Release" / "cfd_ancf_cpp_worker.exe"


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

    def test_input_eof_without_shutdown_is_fail_closed(self) -> None:
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None
        try:
            process.stdin.close()
            process.wait(timeout=10)
            self.assertEqual(process.returncode, 22)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_output_disconnect_is_fail_closed(self) -> None:
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdout.close()
            process.stdin.write(encode_request(request(1))); process.stdin.flush()
            process.stdin.close(); process.wait(timeout=10)
            self.assertEqual(process.returncode, 23)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            if process.stderr is not None and not process.stderr.closed:
                process.stderr.close()

    def test_time_tick_mismatch_is_rejected_before_frame(self) -> None:
        bad = replace(request(2), integer_tick=2209000000)
        with self.assertRaises(FrameError):
            encode_request(bad)

    def test_legacy_worker_rejects_nonzero_bytes_after_fixed_identity_nul(self) -> None:
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None
        try:
            raw = bytearray(encode_request(request(1)))
            run_offset = HEADER.size + 64
            raw[run_offset] = ord("r")
            raw[run_offset + 1] = 0
            raw[run_offset + 2] = ord("x")
            process.stdin.write(raw); process.stdin.flush(); process.stdin.close()
            process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_legacy_worker_rejects_wrong_request_endpoint(self) -> None:
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None
        try:
            raw = bytearray(encode_request(request(1)))
            producer_offset = HEADER.size + 68 + 64 + 64
            raw[producer_offset] = ord("x")
            process.stdin.write(raw); process.stdin.flush(); process.stdin.close()
            process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_request_dimension_limit_is_fail_closed(self) -> None:
        with self.assertRaises(FrameError):
            value = request(1)
            encode_request(StepRequest(**{**value.__dict__, "q": (0.0,) * 2049,
                                          "qdot": (0.0,) * 2049, "force": (0.0,) * 2049}))


if __name__ == "__main__":
    unittest.main()
