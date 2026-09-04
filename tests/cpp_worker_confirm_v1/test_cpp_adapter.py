from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from coupling.cpp_worker_confirm_v1.cpp_adapter import CppAdapterError, CppKernelCampaignAdapter
from coupling.cpp_worker_confirm_v1.contracts import ContractError


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
        arrays = q + tuple(request.qdot) + tuple(request.qddot) + zeros * 4 + q
        payload_hash = hashlib.sha256(struct.pack("<" + "d" * len(arrays), *arrays)).digest()
        return SimpleNamespace(sequence=request.sequence, global_step=request.global_step, case_local_bridge_step=request.case_local_bridge_step,
            time_s=request.time_s, integer_tick=request.integer_tick, request_id=request.request_id,
            transaction_id=request.transaction_id, run_id=request.run_id, case_id=request.case_id,
            ack=1, return_code=0, finite_value_audit=True, q=q, qdot=tuple(request.qdot), qddot=tuple(request.qddot),
            internal_force=zeros, external_force=zeros, generalized_force=zeros,
            predictor=zeros, corrector=q, residual=0.0, iterations=1,
            payload_hash=payload_hash)


def factory(**kwargs): return SimpleNamespace(**kwargs)


class CppAdapterTests(unittest.TestCase):
    class PortableModel:
        ndof = 3
        gauss_order = 3
        mass_gauss_order = 5
        max_newton = 40
        boundary_contract_id = "ancf_v1_bottom_top_xy_zero"
        include_gravity = True
        include_buoyancy = True

        def bytes(self):
            return b"portable-restart-test-model-v1"

    def _adapter(self):
        return CppKernelCampaignAdapter(worker=FakeWorker(), model=object(), request_factory=factory,
            run_id="run", case_id="case", source_global_step=559, source_time_s=2.2075,
            source_tick=2_207_500_000, dt_s=0.00125, q=(0.0, 0.0, 0.0),
            qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0), base_load=(0.0, 0.0, 0.0), slice_count=3)

    def _portable_adapter(self, *, run_id="origin_run", case_id="origin_case"):
        return CppKernelCampaignAdapter(
            worker=FakeWorker(), model=self.PortableModel(), request_factory=factory,
            run_id=run_id, case_id=case_id, source_global_step=559,
            source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
            q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
            base_load=(0.0, 0.0, 0.0), slice_count=3,
            mass_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            strict_numerical_contract=False,
        )

    def _portable_checkpoint(self):
        adapter = self._portable_adapter()
        adapter.start()
        forces = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0))
        adapter.predict(560, 2.20875, forces)
        adapter.correct(560, 2.20875, forces)
        state = adapter.export_pending_restart_state(
            parent_checkpoint_sha256="a" * 64,
            applied_slice_forces_N=forces,
            next_applied_slice_forces_N=forces,
        )
        checkpoint = {
            "committed": True, "global_step": 560, "time_s": 2.20875,
            "integer_tick": 2_208_750_000,
            "checkpoint_metadata": {"ancf_restart_state": state},
        }
        adapter.finalize_committed()
        adapter.shutdown()
        return checkpoint, state

    def _write_checkpoint(self, directory, checkpoint):
        path = Path(directory) / "checkpoint.json"
        path.write_bytes(json.dumps(checkpoint, ensure_ascii=True, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_portable_restart_export_requires_pending_correction_and_serializable_model(self):
        adapter = self._adapter()
        with self.assertRaises(CppAdapterError):
            adapter.export_pending_restart_state(
                parent_checkpoint_sha256="a" * 64,
                applied_slice_forces_N=((0.0, 0.0, 0.0),) * 3,
                next_applied_slice_forces_N=((0.0, 0.0, 0.0),) * 3,
            )
        adapter = self._portable_adapter(); adapter.start()
        forces = ((0.0, 0.0, 0.0),) * 3
        adapter.predict(560, 2.20875, forces)
        with self.assertRaises(CppAdapterError):
            adapter.export_pending_restart_state(
                parent_checkpoint_sha256="a" * 64,
                applied_slice_forces_N=forces, next_applied_slice_forces_N=forces,
            )
        adapter.correct(560, 2.20875, forces)
        state = adapter.export_pending_restart_state(
            parent_checkpoint_sha256="a" * 64,
            applied_slice_forces_N=forces, next_applied_slice_forces_N=forces,
        )
        self.assertEqual(state["global_step"], 560)
        self.assertEqual(state["integer_tick"], 2_208_750_000)
        self.assertEqual(set(state["structure"]), {"q", "qdot", "qddot"})
        self.assertEqual(len(state["applied_slice_forces_N"]), 3)
        adapter.discard_staged(); adapter.shutdown()

    def test_portable_restart_checkpoint_restores_new_identity_and_next_step(self):
        checkpoint, state = self._portable_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path, digest = self._write_checkpoint(directory, checkpoint)
            worker = FakeWorker()
            worker.expected_model_contract_sha256 = state["model_contract_sha256"]
            restored = CppKernelCampaignAdapter.from_checkpoint(
                worker=worker, model=self.PortableModel(), request_factory=factory,
                checkpoint=path, expected_sha256=digest, run_id="new_run", case_id="new_case",
                dt_s=0.00125, base_load=(0.0, 0.0, 0.0), slice_count=3,
                mass_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
                expected_model_contract_sha256=state["model_contract_sha256"],
            )
            self.assertEqual(restored.source_global_step, 560)
            self.assertEqual(restored.source_time_s, 2.20875)
            self.assertEqual(restored.source_tick, 2_208_750_000)
            self.assertEqual(restored.state_view(), state["structure"])
            restored.start()
            prediction, _ = restored.predict(561, 2.21000, ((0.0, 0.0, 0.0),) * 3)
            self.assertEqual(prediction["global_step"], 561)
            self.assertEqual(prediction["case_local_bridge_step"], 1)
            self.assertEqual(prediction["run_id"], "new_run")
            self.assertEqual(prediction["case_id"], "new_case")
            restored.shutdown()

    def test_portable_restart_mutations_and_legacy_barrier_are_rejected(self):
        checkpoint, _state = self._portable_checkpoint()
        mutations = (
            ("state hash", lambda state: state.__setitem__("state_sha256", "0" * 64)),
            ("model hash", lambda state: state.__setitem__("model_contract_sha256", "0" * 64)),
            ("mass hash", lambda state: state.__setitem__("mass_matrix_sha256", "0" * 64)),
            ("time", lambda state: state.__setitem__("time_s", 2.209)),
            ("tick", lambda state: state.__setitem__("integer_tick", 2_208_750_001)),
            ("dt", lambda state: state.__setitem__("dt_s", 0.0025)),
            ("nonfinite", lambda state: state["structure"]["q"].__setitem__(0, "not-a-number")),
            ("force shape", lambda state: state.__setitem__("applied_slice_forces_N", [[0.0, 0.0, 0.0]])),
        )
        with tempfile.TemporaryDirectory() as directory:
            for label, mutate in mutations:
                value = json.loads(json.dumps(checkpoint))
                mutate(value["checkpoint_metadata"]["ancf_restart_state"])
                path, digest = self._write_checkpoint(directory, value)
                with self.assertRaises((ContractError, CppAdapterError), msg=label):
                    CppKernelCampaignAdapter.from_checkpoint(
                        worker=FakeWorker(), model=self.PortableModel(), request_factory=factory,
                        checkpoint=path, expected_sha256=digest, run_id="new_run", case_id="new_case",
                        dt_s=0.00125, base_load=(0.0, 0.0, 0.0), slice_count=3,
                        mass_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
                    )
            legacy = {"committed": True, "global_step": 560, "time_s": 2.20875,
                      "integer_tick": 2_208_750_000, "checkpoint_metadata": {}}
            path, digest = self._write_checkpoint(directory, legacy)
            with self.assertRaises(ContractError):
                CppKernelCampaignAdapter.from_checkpoint(
                    worker=FakeWorker(), model=self.PortableModel(), request_factory=factory,
                    checkpoint=path, expected_sha256=digest, run_id="new_run", case_id="new_case",
                    dt_s=0.00125, base_load=(0.0, 0.0, 0.0), slice_count=3,
                    mass_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
                )

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
                zeros = (0.0,) * n
                arrays = tuple(response.q) + response.qdot + response.qddot + zeros * 4 + tuple(response.q)
                response.payload_hash = hashlib.sha256(
                    struct.pack("<" + "d" * len(arrays), *arrays)
                ).digest()
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
        mass = (1.0, 0.1, 0.2,
                0.1, 2.0, 0.3,
                0.2, 0.3, 3.0)
        adapter = CppKernelCampaignAdapter(worker=worker, model=SimpleNamespace(ndof=3), request_factory=factory,
            run_id="run", case_id="case", source_global_step=559, source_time_s=2.2075,
            source_tick=2_207_500_000, dt_s=0.00125, q=(0.0, 0.0, 0.0),
            qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0), base_load=(0.0, 0.0, 0.0),
            slice_count=3, mass_matrix=mass)
        adapter.start()
        adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
        self.assertEqual(worker.requests[0].mass_matrix, mass)
        adapter.shutdown()

    def test_source_mass_matrix_rejects_asymmetry(self):
        with self.assertRaises(CppAdapterError):
            CppKernelCampaignAdapter(worker=FakeWorker(), model=SimpleNamespace(ndof=3),
                request_factory=factory, run_id="run", case_id="case",
                source_global_step=559, source_time_s=2.2075,
                source_tick=2_207_500_000, dt_s=0.00125,
                q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
                base_load=(0.0, 0.0, 0.0), slice_count=3,
                mass_matrix=(1.0, 0.1, 0.0,
                             0.2, 1.0, 0.0,
                             0.0, 0.0, 1.0))

    def test_identity_mismatch_poisoned_fail_closed(self):
        adapter = self._adapter(); adapter.start()
        with self.assertRaises(CppAdapterError):
            adapter.predict(560, 2.2075, ((0.0, 0.0, 0.0),) * 3)
        adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
        with self.assertRaises(CppAdapterError):
            adapter.correct(560, 2.21000, ((0.0, 0.0, 0.0),) * 3)
        adapter.shutdown()

    def test_response_hash_mismatch_poisoned_fail_closed(self):
        class BadHashWorker(FakeWorker):
            def step(self, request):
                response = super().step(request)
                response.payload_hash = b"x" * 32
                return response

        worker = BadHashWorker()
        adapter = CppKernelCampaignAdapter(
            worker=worker, model=object(), request_factory=factory,
            run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
            q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
            base_load=(0.0, 0.0, 0.0), slice_count=3)
        adapter.start()
        with self.assertRaises(CppAdapterError):
            adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
        self.assertTrue(adapter._terminal)
        with self.assertRaises(CppAdapterError):
            adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)

    def test_missing_response_field_and_string_ack_are_rejected(self):
        class MalformedWorker(FakeWorker):
            def __init__(self, mode):
                super().__init__()
                self.mode = mode

            def step(self, request):
                response = super().step(request)
                if self.mode == "missing":
                    del response.internal_force
                elif self.mode == "bool_ack":
                    response.ack = True
                else:
                    response.ack = "committed"
                return response

        for mode in ("missing", "ack", "bool_ack"):
            adapter = CppKernelCampaignAdapter(
                worker=MalformedWorker(mode), model=object(), request_factory=factory,
                run_id="run", case_id="case", source_global_step=559,
                source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
                q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
                base_load=(0.0, 0.0, 0.0), slice_count=3)
            adapter.start()
            with self.assertRaises(CppAdapterError):
                adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
            self.assertTrue(adapter._terminal)

    def test_checkpoint_round_trip_is_utf8(self):
        adapter = self._adapter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            adapter.save_checkpoint(path)
            adapter.load_checkpoint(path)
            self.assertEqual(len(adapter.state_view()["q"]), 3)

    def test_checkpoint_rejects_model_contract_mutation(self):
        class Model:
            def __init__(self, token):
                self.token = token

            def bytes(self):
                return self.token.encode("ascii")

        def make(model):
            return CppKernelCampaignAdapter(
                worker=FakeWorker(), model=model, request_factory=factory,
                run_id="run", case_id="case", source_global_step=559,
                source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
                q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
                base_load=(0.0, 0.0, 0.0), slice_count=3)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            make(Model("model-a")).save_checkpoint(path)
            with self.assertRaises(CppAdapterError):
                make(Model("model-b")).load_checkpoint(path)

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
            self.assertIn("stdout", worker.audit)
            self.assertIn("stderr", worker.audit)
            self.assertEqual(worker.audit["failure_classification"] if "failure_classification" in worker.audit else None, None)


if __name__ == "__main__": unittest.main()
