from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    FrameError, KernelModel, KernelStepRequest,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import StepRequest


class RepairContractTests(unittest.TestCase):
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

    def test_repair_tool_exists_in_stage_local_directory(self):
        root = ROOT
        self.assertTrue((root / "tools" / "cpp_worker_comprehensive_audit_repair_v1" /
                         "run_ownership_nonzero_base_dual.py").is_file())


if __name__ == "__main__":
    unittest.main()
