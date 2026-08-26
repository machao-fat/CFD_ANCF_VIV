from __future__ import annotations

import os
import subprocess
import unittest
from io import BytesIO
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    HEADER,
    INITIALIZE_ACK,
    MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN,
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
    WORKER_ROLE,
    FrameError,
    StepRequest,
    encode_control,
    encode_request,
)
from coupling.cpp_worker_persistent_ipc_v1.worker_client import (
    PersistentCppWorkerClient,
)
from coupling.cpp_worker_confirm_v1.real_coordinator import _strict_numeric_ack


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "runtime" / "cpp_worker_protocol_lifecycle_repair_v1" / "build-release" / "Release"
LEGACY = BUILD / "cfd_ancf_cpp_worker.exe"
FULL = BUILD / "cfd_ancf_ancf_kernel_worker.exe"


def _request() -> StepRequest:
    return StepRequest(
        sequence=1, global_step=560, case_local_bridge_step=1,
        integer_tick=2_208_750_000, time_s=2.20875, dt_s=0.00125,
        request_id=1, transaction_id=2, run_id="stage190_run", case_id="stage190_case",
        q=(0.0,), qdot=(0.0,), force=(0.0,),
    )


def _ack_frame() -> bytes:
    role = WORKER_ROLE.encode("ascii") + b"\0"
    role += b"\0" * (32 - len(role))
    body = INITIALIZE_ACK.pack(SCHEMA_VERSION, PROTOCOL_VERSION,
                               MESSAGE_INITIALIZE_ACK, role)
    return HEADER.pack(b"CFDANCF1", len(body), MESSAGE_INITIALIZE_ACK) + body


class Stage190ProtocolLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not LEGACY.is_file() or not FULL.is_file():
            raise unittest.SkipTest("Stage190 Release workers have not been built")

    @staticmethod
    def _run_direct(executable: Path, *, legacy_opt_in: bool = False) -> int:
        environment = os.environ.copy()
        environment.pop("CFD_ANCF_OFFLINE_LEGACY_TRANSPORT", None)
        environment.pop("CFD_ANCF_OFFLINE_DIRECT_WORKER", None)
        if legacy_opt_in:
            environment["CFD_ANCF_OFFLINE_LEGACY_TRANSPORT"] = "1"
        process = subprocess.Popen(
            [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(ROOT), env=environment, bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(encode_request(_request()))
            process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            if legacy_opt_in:
                if len(header) != HEADER.size:
                    raise AssertionError("offline legacy worker did not return a response")
                length = HEADER.unpack(header)[1]
                process.stdout.read(length)
                process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
                process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=5)
            return int(process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_legacy_worker_requires_explicit_offline_opt_in(self) -> None:
        self.assertEqual(self._run_direct(LEGACY), 4)

    def test_legacy_worker_offline_opt_in_is_bounded(self) -> None:
        self.assertEqual(self._run_direct(LEGACY, legacy_opt_in=True), 0)

    def test_full_worker_rejects_step_before_initialize(self) -> None:
        environment = os.environ.copy()
        environment.pop("CFD_ANCF_OFFLINE_DIRECT_WORKER", None)
        environment.pop("CFD_ANCF_OFFLINE_LEGACY_TRANSPORT", None)
        process = subprocess.Popen(
            [str(FULL)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(ROOT), env=environment, bufsize=0,
        )
        assert process.stdin is not None
        try:
            # The complete ANCF worker uses the kernel STEP_REQUEST type;
            # the body is intentionally omitted because initialization must
            # be rejected before payload decoding.
            process.stdin.write(HEADER.pack(b"CFDANCF1", 0, 5))
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 4)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_full_worker_initialize_ack_and_shutdown(self) -> None:
        process = subprocess.Popen(
            [str(FULL)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(encode_control(4))
            process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            self.assertEqual(HEADER.unpack(header)[2], MESSAGE_INITIALIZE_ACK)
            body = process.stdout.read(HEADER.unpack(header)[1])
            self.assertEqual(body, _ack_frame()[HEADER.size:])
            process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_python_client_shutdown_requires_initialize_and_close_is_idempotent(self) -> None:
        client = PersistentCppWorkerClient(BytesIO(b""), BytesIO(), timeout_s=0.1)
        with self.assertRaises(FrameError):
            client.shutdown()
        client.close()
        client.close()
        self.assertTrue(client.closed)

    def test_python_client_accepts_only_canonical_initialize_ack(self) -> None:
        client = PersistentCppWorkerClient(BytesIO(_ack_frame()), BytesIO(), timeout_s=0.1)
        client.initialize()
        with self.assertRaises(FrameError):
            client.initialize()
        client.close()

    def test_coordinator_rejects_boolean_float_and_string_ack_values(self) -> None:
        self.assertTrue(_strict_numeric_ack(1))
        for value in (True, 1.0, "ack", "committed", None):
            with self.subTest(value=value):
                self.assertFalse(_strict_numeric_ack(value))


if __name__ == "__main__":
    unittest.main()
