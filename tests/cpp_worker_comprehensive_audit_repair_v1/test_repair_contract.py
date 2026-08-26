from __future__ import annotations

import unittest
import os
import subprocess
import hashlib
import struct
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
BUILD_ROOT = Path(os.environ.get(
    "CFD_ANCF_STAGE_BUILD",
    str(ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "build-release"),
))
SOLVER_SELFTEST = BUILD_ROOT / "Release" / "cfd_ancf_dense_solver_selftest.exe"

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    FrameError, KernelModel, KernelStepRequest, encode_kernel_request,
)
from coupling.cpp_worker_persistent_ipc_v1 import kernel_protocol
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    MESSAGE_INITIALIZE, StepRequest, encode_control,
)

os.environ.setdefault("CFD_ANCF_OFFLINE_DIRECT_WORKER", "1")
WORKER = BUILD_ROOT / "Release" / "cfd_ancf_ancf_kernel_worker.exe"


class RepairContractTests(unittest.TestCase):
    def test_windows_binary_stream_setup_is_checked_and_exceptions_unwind(self):
        project = ROOT / "src" / "coupling"
        sources = (
            project / "cpp_worker_persistent_ipc_v1" / "worker_main.cpp",
            project / "cpp_worker_persistent_ipc_v1" / "ancf_worker_main.cpp",
            project / "cpp_physics_ownership_v1" / "physics_ownership_worker_main.cpp",
        )
        for source in sources:
            text = source.read_text(encoding="utf-8")
            self.assertIn("_setmode(_fileno(stdin), _O_BINARY) == -1", text)
            self.assertIn("_setmode(_fileno(stdout), _O_BINARY) == -1", text)
        cmake = (project / "cpp_worker_persistent_ipc_v1" / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("add_compile_options(/EHsc)", cmake)
        option_line = next(index for index, line in enumerate(cmake.splitlines())
                           if line.strip().startswith("add_compile_options(/EHsc)"))
        target_line = next(index for index, line in enumerate(cmake.splitlines())
                           if line.strip().startswith("add_executable("))
        self.assertLess(option_line, target_line,
                        "/EHsc must be a directory option before targets are declared")

    def model(self) -> KernelModel:
        return KernelModel(elements=2, slices=3, gauss_order=5, max_newton=50,
                           slice_positions_m=(0.0, 5.0, 10.0))

    def request(self) -> KernelStepRequest:
        model = self.model()
        n = model.ndof
        q = [0.0] * n
        for node in range(model.elements + 1):
            q[6 * node + 2] = node * model.length_m / model.elements
            q[6 * node + 5] = 1.0
        return KernelStepRequest(
            sequence=1, global_step=560, case_local_bridge_step=1,
            integer_tick=2208750000, time_s=2.20875, dt_s=0.00125,
            request_id=1, transaction_id=2, run_id="r", case_id="c",
            model=model, q=tuple(q), qdot=(0.0,) * n, qddot=(0.0,) * n,
            base_load=(0.0,) * n, slice_force=(0.0,) * (3 * model.slices),
        )

    def test_zero_global_step_rejected_before_frame(self):
        request = self.request()
        with self.assertRaises(FrameError):
            replace(request, global_step=0).payload()

    def test_zero_identity_tokens_rejected_before_frame(self):
        value = StepRequest(1, 560, 1, 2208750000, 2.20875, 0.00125,
                            1, 2, "r", "c", (0.0,), (0.0,), (0.0,))
        with self.assertRaises(FrameError):
            replace(value, request_id=0).payload()
        with self.assertRaises(FrameError):
            replace(value, transaction_id=0).payload()

    def test_nonzero_damping_is_fail_closed_until_implemented(self):
        with self.assertRaises(FrameError):
            replace(self.request(), model=replace(self.model(), damping_alpha=1.0)).payload()

    def test_model_dimension_upper_bound_rejected(self):
        request = self.request()
        with self.assertRaises(FrameError):
            replace(request, model=replace(request.model, elements=10001)).payload()

    def test_dense_matrix_memory_bound_is_rejected(self):
        request = self.request()
        with self.assertRaises(FrameError):
            replace(request, model=replace(request.model, elements=400)).payload()

    def test_newton_budget_is_bounded_before_frame(self):
        request = self.request()
        with self.assertRaises(FrameError):
            replace(request, model=replace(request.model, max_newton=1001)).payload()

    def test_nonmonotone_slice_positions_are_rejected(self):
        request = self.request()
        with self.assertRaises(FrameError):
            replace(request, model=replace(request.model, slice_positions_m=(0.0, 6.0, 5.0))).payload()

    def test_slice_position_count_is_rejected(self):
        request = self.request()
        with self.assertRaises(FrameError):
            replace(request, model=replace(request.model, slice_positions_m=(0.0, 10.0))).payload()

    def test_time_tick_mismatch_is_rejected_before_frame(self):
        request = self.request()
        with self.assertRaises(FrameError):
            replace(request, integer_tick=request.integer_tick + 1).payload()

    def test_asymmetric_mass_matrix_is_rejected_before_frame(self):
        request = self.request()
        n = request.model.ndof
        mass = [0.0] * (n * n)
        for index in range(n):
            mass[index * n + index] = 1.0
        mass[1] = 1.0e-12
        with self.assertRaises(FrameError):
            replace(request, mass_matrix=tuple(mass)).payload()

    @unittest.skipUnless(WORKER.is_file(), "Stage-local C++ kernel worker has not been built")
    def test_cpp_worker_rejects_tampered_asymmetric_mass_matrix(self):
        request = self.request()
        n = request.model.ndof
        mass = [0.0] * (n * n)
        for index in range(n):
            mass[index * n + index] = 1.0
        frame = bytearray(encode_kernel_request(replace(request, mass_matrix=tuple(mass))))
        payload_offset = kernel_protocol.HEADER.size
        model_size = kernel_protocol._MODEL.size + 8 * request.model.slices
        model_offset = payload_offset + kernel_protocol._PREFIX.size
        sizes_offset = model_offset + model_size
        ids_size = (kernel_protocol.ID_RUN + kernel_protocol.ID_CASE +
                    2 * kernel_protocol.ID_ENDPOINT)
        digest_offset = sizes_offset + 12 + ids_size
        arrays_offset = digest_offset + 32
        mass_offset = arrays_offset + 4 * n * 8
        struct.pack_into("<d", frame, mass_offset + 8, 1.0e-12)
        model_bytes = bytes(frame[model_offset:sizes_offset])
        arrays = bytes(frame[arrays_offset:])
        frame[digest_offset:digest_offset + 32] = hashlib.sha256(model_bytes + arrays).digest()
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None
        try:
            process.stdin.write(frame)
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    @unittest.skipUnless(WORKER.is_file(), "Stage-local C++ kernel worker has not been built")
    def test_cpp_worker_rejects_duplicate_initialize_control(self):
        process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=str(ROOT), bufsize=0)
        assert process.stdin is not None
        try:
            process.stdin.write(encode_control(MESSAGE_INITIALIZE))
            process.stdin.write(encode_control(MESSAGE_INITIALIZE))
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=10)
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_repair_tool_exists_in_stage_local_directory(self):
        root = ROOT
        self.assertTrue((root / "tools" / "cpp_worker_comprehensive_audit_repair_v1" /
                         "run_ownership_nonzero_base_dual.py").is_file())

    def test_dense_solver_second_pivot_regression(self):
        self.assertTrue(SOLVER_SELFTEST.is_file(), "dense solver selftest must be built before this test")
        completed = subprocess.run([str(SOLVER_SELFTEST)], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("second_pivot=1", completed.stdout)


if __name__ == "__main__":
    unittest.main()
