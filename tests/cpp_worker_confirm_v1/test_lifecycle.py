from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_confirm_v1.lifecycle import LifecycleError, ResidentCppWorkerLifecycle
from coupling.cpp_worker_confirm_v1.production_factory import bind_cpp_worker_lifecycle
from coupling.cpp_worker_confirm_v1.barrier import Stage100SliceBarrier
from coupling.cpp_worker_confirm_v1.contracts import CppConfirmContract, REAL_AUTHORIZATION_TOKEN
from coupling.cpp_worker_confirm_v1.real_coordinator import CppConfirmRun
from coupling.performance_optimization_v2.coordinator import SliceResult, canonical_hash


class Worker:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.owned_residual = 0
        self.requests = []

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def step(self, request):
        self.requests.append(request)
        n = len(request.q)
        zeros = tuple(0.0 for _ in range(n))
        q = tuple(value + 1.0e-6 for value in request.q)
        arrays = q + tuple(request.qdot) + tuple(request.qddot) + zeros * 4 + q
        payload_hash = hashlib.sha256(struct.pack("<" + "d" * len(arrays), *arrays)).digest()
        return SimpleNamespace(
            sequence=request.sequence, global_step=request.global_step,
            case_local_bridge_step=request.case_local_bridge_step,
            time_s=request.time_s, integer_tick=request.integer_tick,
            request_id=request.request_id, transaction_id=request.transaction_id,
            run_id=request.run_id, case_id=request.case_id, ack=1,
            return_code=0, finite_value_audit=True,
            q=q,
            qdot=tuple(request.qdot), qddot=tuple(request.qddot),
            internal_force=zeros, external_force=zeros, generalized_force=zeros,
            predictor=zeros, corrector=q, residual=0.0, iterations=1,
            payload_hash=payload_hash,
        )


def request_factory(**kwargs):
    return SimpleNamespace(**kwargs)


class Slice:
    def __init__(self, sid: int, root: Path) -> None:
        self.slice_id = sid
        self.root = root
        self.starts = 0
        self.start_count = 0
        self.stops = 0
        self.owned_residual = 0

    def start(self) -> None:
        self.starts += 1
        self.start_count += 1

    def advance(self, identity, motion):
        payload = {"slice_id": self.slice_id, "global_step": identity.global_step,
                   "case_local_bridge_step": identity.case_local_bridge_step,
                   "time_s": identity.time_s, "integer_tick": identity.integer_tick,
                   "ack": "consumed", "load": {"force_x_N": 1.0, "force_y_N": 0.0,
                                                   "force_z_N": 0.0}}
        return SliceResult(self.slice_id, identity, payload, canonical_hash(payload), 0,
                           7000 + self.slice_id, 0.0)

    def finalize_step(self, identity) -> None:
        return None

    def stop(self) -> None:
        self.stops += 1


class LifecycleTests(unittest.TestCase):
    def _adapter(self, run_id: str = "run", case_id: str = "case"):
        return CppKernelCampaignAdapter(
            worker=Worker(), model=object(), request_factory=request_factory,
            run_id=run_id, case_id=case_id, source_global_step=559,
            source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
            q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
            base_load=(0.0, 0.0, 0.0), slice_count=3)

    def test_bound_adapter_is_single_start_and_single_stop(self):
        adapter = self._adapter()
        lifecycle = bind_cpp_worker_lifecycle(adapter)
        lifecycle.start()
        with self.assertRaises(LifecycleError): lifecycle.start()
        for step in (560, 561):
            t = 2.2075 + (step - 559) * 0.00125
            adapter.predict(step, t, ((0.0, 0.0, 0.0),) * 3)
            adapter.correct(step, t, ((0.0, 0.0, 0.0),) * 3)
            adapter.finalize_committed()
        lifecycle.stop(); lifecycle.stop()
        self.assertEqual(adapter.worker.started, 1)
        self.assertEqual(adapter.worker.stopped, 1)
        self.assertEqual(len(adapter.worker.requests), 4)

    def test_resident_worker_and_three_slice_barrier_commit_only_after_all_slices(self):
        adapter = self._adapter()
        lifecycle = ResidentCppWorkerLifecycle(adapter)
        engines = {}
        def factory(sid, path):
            engines[sid] = Slice(sid, path)
            return engines[sid]
        with tempfile.TemporaryDirectory() as directory:
            barrier = Stage100SliceBarrier(
                run_id="run", case_id="case", source_global_step=559,
                source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
                runtime=Path(directory), engine_factory=factory, parallel=True)
            lifecycle.start(); barrier.start()
            for step in (560, 561):
                t = 2.2075 + (step - 559) * 0.00125
                prediction, _ = adapter.predict(step, t, ((0.0, 0.0, 0.0),) * 3)
                prepared = barrier.prepare_step(
                    global_step=step, time_s=t,
                    motion_by_slice={sid: {"global_step": step, "prediction": prediction}
                                     for sid in range(3)})
                self.assertTrue(prepared["prepared"])
                self.assertEqual(len(barrier.records), step - 560)
                correction, _ = adapter.correct(step, t, ((1.0, 0.0, 0.0),) * 3)
                committed = barrier.commit_prepared(worker_response=correction)
                adapter.finalize_committed()
                self.assertTrue(committed["committed"])
            barrier.stop(); lifecycle.stop()
        self.assertEqual(adapter.worker.started, 1)
        self.assertEqual(adapter.worker.stopped, 1)
        self.assertEqual([engines[sid].starts for sid in range(3)], [1, 1, 1])
        self.assertEqual([engines[sid].stops for sid in range(3)], [1, 1, 1])
        self.assertEqual(len(barrier.records), 2)
        self.assertEqual(adapter.owned_residual, 0)

    def test_lifecycle_rejects_adapter_without_cleanup(self):
        with self.assertRaises(LifecycleError): ResidentCppWorkerLifecycle(object())

    def test_cpp_confirm_run_uses_wrapper_for_production_start_and_stop(self):
        project_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=project_root) as directory:
            root = Path(directory)
            source = root / "accepted_source.json"
            source.write_text(json.dumps({
                "status": "committed", "step": 559, "time_s": 2.2075,
                "time_tick": 2207500000,
                "structure": {"q": [0.0, 0.0, 0.0], "qdot": [0.0, 0.0, 0.0],
                               "qddot": [0.0, 0.0, 0.0]},
            }, sort_keys=True) + "\n", encoding="utf-8")
            contract = CppConfirmContract(
                stage_id="stage4f_d_cpp_worker_lifecycle_real_003",
                run_id="cpp_worker_lifecycle_003", case_id="cpp_worker_lifecycle_case_003",
                runtime=root / "runtime", results=root / "results",
                source_checkpoint=source,
                source_checkpoint_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                allow_real_external_processes=True, authorization=REAL_AUTHORIZATION_TOKEN,
            )
            adapter = self._adapter(run_id=contract.run_id, case_id=contract.case_id)
            lifecycle = bind_cpp_worker_lifecycle(adapter)
            engines = {}
            def factory(sid, path):
                engines[sid] = Slice(sid, path)
                return engines[sid]
            run = CppConfirmRun(contract, lifecycle, factory, authorization=REAL_AUTHORIZATION_TOKEN)
            run.preflight(root)
            run.start()
            record = run.commit_step_with_cpp_adapter(
                global_step=560, time_s=2.20875, adapter=lifecycle,
                previous_slice_forces={sid: (0.0, 0.0, 0.0) for sid in range(3)},
                motion_builder=lambda prediction, sid: {"slice_id": sid, "global_step": prediction["global_step"]},
            )
            summary = run.stop()
            self.assertTrue(record["committed"])
            self.assertEqual(summary["committed_steps"], 1)
            self.assertEqual(summary["worker_start_count"], 1)
            self.assertEqual(summary["slice_start_counts"], [1, 1, 1])
            self.assertEqual(summary["owned_residual"], 0)
            self.assertEqual(adapter.worker.started, 1)
            self.assertEqual(adapter.worker.stopped, 1)


if __name__ == "__main__":
    unittest.main()
