from __future__ import annotations

import subprocess
import unittest
import os
from dataclasses import replace
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src" / "coupling"))
sys.path.insert(0, str(_ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    HEADER, MAGIC, MESSAGE_KERNEL_STEP_RESPONSE, KernelModel, KernelStepRequest,
    decode_kernel_response, encode_kernel_request, validate_kernel_response,
)


ROOT = Path(__file__).resolve().parents[2]
_BUILD_ROOT = Path(os.environ.get(
    "CFD_ANCF_STAGE_BUILD",
    str(ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "stage158_build"),
))
WORKER = _BUILD_ROOT / "Release" / "cfd_ancf_physics_ownership_worker.exe"


def model() -> KernelModel:
    return KernelModel(length_m=10.0, diameter_m=1.0, inner_diameter_m=0.9,
                       elements=2, slices=3, top_tension_N=1.0e6,
                       youngs_modulus_Pa=2.07e11, material_density=7850.0,
                       fluid_density=1025.0, gravity=9.81, gauss_order=5,
                       max_newton=50, slice_positions_m=(0.0, 5.0, 10.0))


def expected_base(value: KernelModel) -> tuple[float, ...]:
    from tools.cpp_physics_ownership_v1.run_offline_validation import expected_base as reference
    return tuple(reference(value))


def request(value: KernelModel, base: tuple[float, ...], bridge: int = 1) -> KernelStepRequest:
    q = [0.0] * value.ndof
    for node in range(value.elements + 1):
        q[6 * node + 2] = node * value.length_m / value.elements
        q[6 * node + 5] = 1.0
    return KernelStepRequest(
        sequence=1, global_step=560, case_local_bridge_step=bridge,
        integer_tick=2208750000, time_s=2.20875, dt_s=0.00125,
        request_id=153100, transaction_id=15310000,
        run_id="stage153_test_run", case_id="stage153_test_case", model=value,
        q=tuple(q), qdot=(0.0,) * value.ndof, qddot=(0.0,) * value.ndof,
        base_load=base, slice_force=(0.0,) * (3 * value.slices),
    )


def request_for_model(value: KernelModel, base: tuple[float, ...], sequence: int,
                      global_step: int, bridge: int, request_id: int) -> KernelStepRequest:
    q = [0.0] * value.ndof
    for node in range(value.elements + 1):
        q[6 * node + 2] = node * value.length_m / value.elements
        q[6 * node + 5] = 1.0
    return KernelStepRequest(
        sequence=sequence, global_step=global_step, case_local_bridge_step=bridge,
        integer_tick=2_208_750_000 + (sequence - 1) * 1_250_000,
        time_s=2.20875 + (sequence - 1) * 0.00125, dt_s=0.00125,
        request_id=request_id, transaction_id=request_id + 10_000_000,
        run_id="stage153_dimension_lineage_run", case_id="stage153_dimension_lineage_case",
        model=value, q=tuple(q), qdot=(0.0,) * value.ndof,
        qddot=(0.0,) * value.ndof, base_load=base,
        slice_force=(0.0,) * (3 * value.slices),
    )


def exchange(value: KernelStepRequest):
    process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
    response = None
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(encode_kernel_request(value))
        process.stdin.flush()
        header = process.stdout.read(HEADER.size)
        if len(header) == HEADER.size:
            magic, length, message_type = HEADER.unpack(header)
            if magic == MAGIC and message_type == MESSAGE_KERNEL_STEP_RESPONSE:
                body = process.stdout.read(length)
                response = decode_kernel_response(header + body)
                process.stdin.write(HEADER.pack(MAGIC, 0, 3))
                process.stdin.flush()
                process.stdin.close()
                process.wait(timeout=10)
                return response, process.returncode
        process.kill()
        process.wait(timeout=10)
        return None, process.returncode
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


class OwnershipWorkerRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not WORKER.is_file():
            raise unittest.SkipTest("Stage 153 Release worker has not been built")

    def test_nonzero_base_is_reference_not_second_load(self):
        value = model()
        base = expected_base(value)
        response, code = exchange(request(value, base))
        self.assertIsNotNone(response)
        self.assertEqual(code, 0)
        validate_kernel_response(request(value, base), response)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(response.external_force, base)), 1e-8)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(response.generalized_force, base)), 1e-8)

    def test_input_eof_without_shutdown_is_fail_closed(self):
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

    def test_output_disconnect_is_fail_closed(self):
        value = model()
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdout.close()
            process.stdin.write(encode_kernel_request(request(value, expected_base(value))))
            process.stdin.flush(); process.stdin.close(); process.wait(timeout=10)
            self.assertEqual(process.returncode, 23)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            if process.stderr is not None and not process.stderr.closed:
                process.stderr.close()

    def test_mismatched_base_fails_closed(self):
        value = model()
        response, code = exchange(request(value, (0.0,) * value.ndof))
        self.assertIsNone(response)
        self.assertNotEqual(code, 0)

    def test_endpoint_identity_mismatch_fails_closed(self):
        value = model()
        base = expected_base(value)
        req = request(value, base)
        raw = bytearray(encode_kernel_request(req))
        from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import ID_CASE, ID_ENDPOINT, ID_RUN, _PREFIX
        producer_offset = HEADER.size + _PREFIX.size + len(req.model.bytes()) + 8 + ID_RUN + ID_CASE
        raw[producer_offset:producer_offset + ID_ENDPOINT] = b"untrusted_sender\0" + b"\0" * (ID_ENDPOINT - len("untrusted_sender") - 1)
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        try:
            assert process.stdin is not None
            process.stdin.write(bytes(raw)); process.stdin.flush(); process.stdin.close()
            process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_first_bridge_step_must_start_at_one(self):
        value = model()
        response, code = exchange(request(value, expected_base(value), bridge=2))
        self.assertIsNone(response)
        self.assertNotEqual(code, 0)

    def test_response_dimension_and_checkpoint_time_are_checked(self):
        value = model()
        base = expected_base(value)
        req = request(value, base)
        response, code = exchange(req)
        self.assertEqual(code, 0)
        self.assertIsNotNone(response)
        with self.assertRaises(Exception):
            validate_kernel_response(req, replace(response, q=response.q[:-1]))
        with self.assertRaises(Exception):
            validate_kernel_response(req, replace(response, checkpoint_time_s=response.checkpoint_time_s + 1.0))

    def test_duplicate_request_and_transaction_fail_closed_in_worker(self):
        value = model()
        base = expected_base(value)
        first = request(value, base)
        second = replace(first, sequence=2, global_step=561, case_local_bridge_step=2,
                         integer_tick=2210000000, time_s=2.2100)
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(encode_kernel_request(first)); process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            body = process.stdout.read(HEADER.unpack(header)[1])
            validate_kernel_response(first, decode_kernel_response(header + body))
            process.stdin.write(encode_kernel_request(second)); process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            if process.stdout is not None and not process.stdout.closed:
                process.stdout.close()
            if process.stderr is not None and not process.stderr.closed:
                process.stderr.close()

    def test_contiguous_lineage_advances_past_second_step(self):
        value = model()
        base = expected_base(value)
        first = request(value, base)
        second = replace(first, sequence=2, global_step=561, case_local_bridge_step=2,
                         integer_tick=2210000000, time_s=2.2100,
                         request_id=153101, transaction_id=15310100)
        third = replace(second, sequence=3, global_step=562, case_local_bridge_step=3,
                        integer_tick=2211250000, time_s=2.21125,
                        request_id=153102, transaction_id=15310200)
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None and process.stdout is not None
        try:
            for item in (first, second, third):
                process.stdin.write(encode_kernel_request(item)); process.stdin.flush()
                header = process.stdout.read(HEADER.size)
                self.assertEqual(len(header), HEADER.size)
                body = process.stdout.read(HEADER.unpack(header)[1])
                response = decode_kernel_response(header + body)
                validate_kernel_response(item, response)
            process.stdin.write(HEADER.pack(MAGIC, 0, 3)); process.stdin.flush()
            process.stdin.close(); process.wait(timeout=10)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_profile_write_failure_is_not_silent(self):
        value = model()
        base = expected_base(value)
        missing_profile = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "missing-profile-dir" / "profile.jsonl"
        env = os.environ.copy()
        env["CFD_ANCF_PROFILE_PATH"] = str(missing_profile)
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0, env=env)
        assert process.stdin is not None
        try:
            process.stdin.write(encode_kernel_request(request(value, base))); process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_structural_dimension_mutation_is_fail_closed(self):
        value = model()
        first = request_for_model(value, expected_base(value), 1, 560, 1, 153200)
        changed = replace(value, elements=3)
        second = request_for_model(changed, expected_base(changed), 2, 561, 2, 153201)
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(encode_kernel_request(first)); process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            self.assertEqual(len(header), HEADER.size)
            body = process.stdout.read(HEADER.unpack(header)[1])
            validate_kernel_response(first, decode_kernel_response(header + body))
            process.stdin.write(encode_kernel_request(second)); process.stdin.flush()
            process.stdin.close(); process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()


if __name__ == "__main__":
    unittest.main()
