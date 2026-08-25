from __future__ import annotations

import math
import unittest
from dataclasses import replace

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel,
    KernelStepRequest,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    FrameError,
    StepRequest,
    canonical_integer_tick,
)


class Stage183ContractTests(unittest.TestCase):
    def test_half_nanosecond_rounding_matches_cpp_llround(self) -> None:
        self.assertEqual(canonical_integer_tick(0.5e-9), 1)
        self.assertEqual(canonical_integer_tick(1.5e-9), 2)
        self.assertEqual(canonical_integer_tick(2.5e-9), 3)

    def test_negative_and_nonfinite_tick_inputs_fail_closed(self) -> None:
        for value in (-1.0e-9, math.nan, math.inf):
            with self.assertRaises(FrameError):
                canonical_integer_tick(value)

    def test_step_request_uses_canonical_tick(self) -> None:
        request = StepRequest(
            sequence=1, global_step=1, case_local_bridge_step=1,
            integer_tick=1, time_s=0.5e-9, dt_s=0.1e-9,
            request_id=1, transaction_id=2, run_id="run", case_id="case",
            q=(0.0,), qdot=(0.0,), force=(0.0,),
        )
        request.payload()
        with self.assertRaises(FrameError):
            replace(request, integer_tick=0).payload()

    def test_kernel_request_uses_canonical_tick(self) -> None:
        model = KernelModel(elements=1, slices=1)
        n = model.ndof
        request = KernelStepRequest(
            sequence=1, global_step=1, case_local_bridge_step=1,
            integer_tick=1, time_s=0.5e-9, dt_s=0.1e-9,
            request_id=1, transaction_id=2, run_id="run", case_id="case",
            model=model, q=(0.0,) * n, qdot=(0.0,) * n,
            qddot=(0.0,) * n, base_load=(0.0,) * n, slice_force=(0.0,) * 3,
        )
        request.payload()
        with self.assertRaises(FrameError):
            replace(request, integer_tick=0).payload()


if __name__ == "__main__":
    unittest.main()
