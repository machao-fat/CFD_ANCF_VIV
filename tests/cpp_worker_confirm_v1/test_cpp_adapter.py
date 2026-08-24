from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from coupling.cpp_worker_confirm_v1.cpp_adapter import CppAdapterError, CppKernelCampaignAdapter


class FakeWorker:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.owned_residual = 0
        self.requests = []

    def start(self): self.started += 1
    def stop(self): self.stopped += 1
    def step(self, request):
        self.requests.append(request)
        n = len(request.q)
        q = tuple(value + 1.0e-6 for value in request.q)
        zeros = tuple(0.0 for _ in range(n))
        return SimpleNamespace(sequence=request.sequence, global_step=request.global_step, case_local_bridge_step=request.case_local_bridge_step,
            time_s=request.time_s, integer_tick=request.integer_tick, request_id=request.request_id,
            transaction_id=request.transaction_id, run_id=request.run_id, case_id=request.case_id,
            ack=1, return_code=0, finite_value_audit=True, q=q, qdot=tuple(request.qdot), qddot=tuple(request.qddot),
            generalized_force=zeros, payload_hash=b"h" * 32)


def factory(**kwargs): return SimpleNamespace(**kwargs)


class CppAdapterTests(unittest.TestCase):
    def _adapter(self):
        return CppKernelCampaignAdapter(worker=FakeWorker(), model=object(), request_factory=factory,
            run_id="run", case_id="case", source_global_step=559, source_time_s=2.2075,
            source_tick=2_207_500_000, dt_s=0.00125, q=(0.0, 0.0, 0.0),
            qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0), base_load=(0.0, 0.0, 0.0), slice_count=3)

    def test_one_worker_handles_multiple_staged_steps(self):
        adapter = self._adapter(); adapter.start()
        for step in (560, 561):
            time_s = 2.2075 + (step - 559) * 0.00125
            adapter.predict(step, time_s, ((0.0, 0.0, 0.0),) * 3)
            adapter.correct(step, time_s, ((0.0, 0.0, 0.0),) * 3)
            adapter.finalize_committed()
        self.assertEqual(adapter.worker.started, 1)
        self.assertEqual(len(adapter.worker.requests), 4)
        self.assertEqual([item.sequence for item in adapter.worker.requests], [1, 2, 3, 4])
        self.assertEqual([item.request_id for item in adapter.worker.requests], [100001, 100002, 100003, 100004])
        adapter.shutdown(); self.assertEqual(adapter.worker.stopped, 1)

    def test_prediction_exposes_one_consistent_motion_state(self):
        adapter = self._adapter(); adapter.start()
        prediction, _ = adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
        self.assertEqual(len(prediction["predictor"]), 3)
        self.assertEqual(prediction["predictor_qdot"], [0.0, 0.0, 0.0])
        self.assertEqual(prediction["predictor_qddot"], [0.0, 0.0, 0.0])
        adapter.shutdown()

    def test_prediction_motion_uses_complete_worker_response_state(self):
        class ResponseStateWorker(FakeWorker):
            def step(self, request):
                response = super().step(request)
                n = len(request.q)
                response.qdot = tuple(10.0 + index for index in range(n))
                response.qddot = tuple(20.0 + index for index in range(n))
                return response

        worker = ResponseStateWorker()
        adapter = CppKernelCampaignAdapter(worker=worker, model=object(), request_factory=factory,
            run_id="run", case_id="case", source_global_step=559, source_time_s=2.2075,
            source_tick=2_207_500_000, dt_s=0.00125, q=(0.0, 0.0, 0.0),
            qdot=(1.0, 2.0, 3.0), qddot=(4.0, 5.0, 6.0), base_load=(0.0, 0.0, 0.0), slice_count=3)
        adapter.start()
        prediction, _ = adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
        self.assertEqual(prediction["predictor_qdot"], [10.0, 11.0, 12.0])
        self.assertEqual(prediction["predictor_qddot"], [20.0, 21.0, 22.0])
        self.assertEqual(prediction["motion"], prediction["predictor"])
        adapter.shutdown()

    def test_source_mass_matrix_is_forwarded_on_every_request(self):
        worker = FakeWorker()
        adapter = CppKernelCampaignAdapter(worker=worker, model=SimpleNamespace(ndof=3), request_factory=factory,
            run_id="run", case_id="case", source_global_step=559, source_time_s=2.2075,
            source_tick=2_207_500_000, dt_s=0.00125, q=(0.0, 0.0, 0.0),
            qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0), base_load=(0.0, 0.0, 0.0),
            slice_count=3, mass_matrix=tuple(float(index) for index in range(9)))
        adapter.start()
        adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
        self.assertEqual(worker.requests[0].mass_matrix, tuple(float(index) for index in range(9)))
        adapter.shutdown()

    def test_identity_mismatch_poisoned_fail_closed(self):
        adapter = self._adapter(); adapter.start()
        with self.assertRaises(CppAdapterError):
            adapter.predict(560, 2.2075, ((0.0, 0.0, 0.0),) * 3)
        adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
        with self.assertRaises(CppAdapterError):
            adapter.correct(560, 2.21000, ((0.0, 0.0, 0.0),) * 3)
        adapter.shutdown()

    def test_checkpoint_round_trip_is_utf8(self):
        adapter = self._adapter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            adapter.save_checkpoint(path)
            adapter.load_checkpoint(path)
            self.assertEqual(len(adapter.state_view()["q"]), 3)

    def test_release_worker_accepts_two_transport_requests_per_logical_step(self):
        from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker, _fixture
        from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
        model, q, qdot, qddot, base_load = _fixture()
        with tempfile.TemporaryDirectory() as directory:
            worker = KernelWorker(
                Path(__file__).resolve().parents[2] / "runtime" /
                "cpp_worker_persistent_ipc_v1" / "build-release" /
                "cfd_ancf_ancf_kernel_worker.exe",
                Path(directory) / "process", "run", "case")
            adapter = CppKernelCampaignAdapter(
                worker=worker, model=model, request_factory=KernelStepRequest,
                run_id="run", case_id="case", source_global_step=559,
                source_time_s=2.2075, source_tick=2207500000, dt_s=.00125,
                q=q, qdot=qdot, qddot=qddot, base_load=base_load, slice_count=3)
            adapter.start()
            zero = ((0.0, 0.0, 0.0),) * 3
            for step in (560, 561):
                t = 2.2075 + (step - 559) * .00125
                adapter.predict(step, t, zero)
                adapter.correct(step, t, zero)
                adapter.finalize_committed()
            adapter.shutdown()
            self.assertEqual(adapter.start_count, 1)
            self.assertEqual([item["transport_sequence"] for item in adapter.responses if "transport_sequence" in item], [1, 2, 3, 4])
            self.assertEqual(adapter.owned_residual, 0)


if __name__ == "__main__": unittest.main()
