from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    HEADER, KernelModel, KernelStepRequest, decode_kernel_response,
    encode_kernel_request, validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import FrameError, encode_control, MESSAGE_SHUTDOWN


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "build-release" / "cfd_ancf_ancf_kernel_worker.exe"


def request(sequence: int, global_step: int) -> KernelStepRequest:
    model = KernelModel(length_m=10.0, diameter_m=1.0, inner_diameter_m=0.9,
                        elements=2, slices=3, top_tension_N=0.0,
                        newton_tolerance=1.0e-4)
    q = [0.0] * model.ndof
    qdot = [0.0] * model.ndof
    qddot = [0.0] * model.ndof
    for node in range(model.elements + 1):
        base = 6 * node
        q[base + 2] = node * model.length_m / model.elements
        q[base + 5] = 1.0
    return KernelStepRequest(
        sequence=sequence, global_step=global_step, case_local_bridge_step=sequence,
        integer_tick=sequence * 1_000_000, time_s=sequence * 0.001, dt_s=0.001,
        request_id=10_000 + sequence, transaction_id=20_000 + sequence,
        run_id="kernel_worker_offline_run", case_id="kernel_worker_offline_case",
        model=model, q=tuple(q), qdot=tuple(qdot), qddot=tuple(qddot),
        base_load=tuple([0.0] * model.ndof), slice_force=tuple([0.0] * (3 * model.slices)),
    )


class KernelWorkerTests(unittest.TestCase):
    def test_persistent_kernel_worker_processes_two_steps(self) -> None:
        self.assertTrue(WORKER.is_file(), "kernel worker must be built before this test")
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for sequence, global_step in ((1, 560), (2, 561)):
                value = request(sequence, global_step)
                process.stdin.write(encode_kernel_request(value)); process.stdin.flush()
                header = process.stdout.read(HEADER.size)
                self.assertEqual(len(header), HEADER.size)
                length = HEADER.unpack(header)[1]
                body = process.stdout.read(length)
                response = decode_kernel_response(header + body)
                validate_kernel_response(value, response)
                self.assertEqual(response.checkpoint_step, global_step)
                self.assertTrue(response.finite_value_audit)
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

    def test_kernel_request_rejects_nan_before_frame(self) -> None:
        value = request(1, 560)
        with self.assertRaises(FrameError):
            encode_kernel_request(KernelStepRequest(**{**value.__dict__, "q": (float("nan"),) + value.q[1:]}))


if __name__ == "__main__":
    unittest.main()
