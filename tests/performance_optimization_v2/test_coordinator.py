from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from coupling.performance_optimization_v2.coordinator import CoordinatorError, OpenFOAMProcessEngine, PersistentSliceCoordinator, SliceResult, StepIdentity, canonical_hash


class MockEngine:
    def __init__(self, sid: int, path: Path, fault: str | None = None): self.slice_id, self.path, self.fault, self.start_count, self.stop_count = sid, path, fault, 0, 0
    def start(self): self.start_count += 1
    def advance(self, identity: StepIdentity):
        if self.fault == "disconnect": raise RuntimeError("injected disconnect")
        if self.slice_id == 0: time.sleep(.01)
        payload = {"slice_id": self.slice_id, "force_y_N": float(self.slice_id + 1)}
        if self.fault == "identity": identity = StepIdentity(identity.run_id, identity.case_id, identity.source_global_step, identity.source_time_s, identity.source_tick, identity.global_step, identity.case_local_bridge_step + 1, identity.time_s, identity.integer_tick, identity.request_id, identity.transaction_id)
        code = 1 if self.fault == "nonzero" else 0
        return SliceResult(self.slice_id, identity, payload, canonical_hash(payload), code, 1000 + self.slice_id, .0)
    def stop(self): self.stop_count += 1
    @property
    def owned_residual(self): return 0


class CoordinatorTests(unittest.TestCase):
    def make(self, *, fault: int | None = None, parallel: bool = True):
        engines = {}
        def factory(sid, path):
            engines[sid] = MockEngine(sid, path, "disconnect" if fault == sid else None); return engines[sid]
        coordinator = PersistentSliceCoordinator(run_id="run95", case_id="case95", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, dt_s=.00125,
            runtime=Path(tempfile.mkdtemp()), parallel=parallel, engine_factory=factory)
        return coordinator, engines

    def test_each_slice_starts_once_and_bridge_is_local(self):
        coordinator, engines = self.make(); coordinator.start()
        record = coordinator.advance_step(global_step=560, time_s=2.20875)
        self.assertEqual(record["case_local_bridge_step"], 1); self.assertEqual(record["slice_ids"], [0, 1, 2])
        coordinator.advance_step(global_step=561, time_s=2.21); coordinator.stop()
        self.assertEqual([engines[i].start_count for i in range(3)], [1, 1, 1]); self.assertEqual(coordinator.owned_residual, 0)

    def test_failure_poisoned_before_commit(self):
        coordinator, engines = self.make(fault=1); coordinator.start()
        with self.assertRaises(CoordinatorError): coordinator.advance_step(global_step=560, time_s=2.20875)
        self.assertTrue(coordinator.failed); self.assertFalse((coordinator.runtime / "checkpoint" / "checkpoint_00000560.json").exists())

    def test_bad_mapping_rejected(self):
        with self.assertRaises(CoordinatorError): StepIdentity.create(run_id="r", case_id="c", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, global_step=560, time_s=2.20875, dt_s=.002)

    def test_identity_and_nonzero_are_fail_closed(self):
        for mode in ("identity", "nonzero"):
            engines = {}
            def factory(sid, path, mode=mode):
                engines[sid] = MockEngine(sid, path, mode if sid == 2 else None); return engines[sid]
            coordinator = PersistentSliceCoordinator(run_id="run95_" + mode, case_id="case95", source_global_step=559,
                source_time_s=2.2075, source_tick=2207500000, dt_s=.00125, runtime=Path(tempfile.mkdtemp()), engine_factory=factory)
            coordinator.start()
            with self.assertRaises(CoordinatorError): coordinator.advance_step(global_step=560, time_s=2.20875)
            self.assertTrue(coordinator.failed)

    def test_openfoam_process_engine_starts_once_and_cleans_owned_pid(self):
        class Process:
            pid = 7777; returncode = 0
            def poll(self): return None
            def terminate(self): self.returncode = 0
            def wait(self, timeout=None): return 0
        calls = []
        def launcher(command, **kwargs): calls.append((command, kwargs)); return Process()
        engine = OpenFOAMProcessEngine(slice_id=0, case_dir=Path(tempfile.mkdtemp()), command=["wsl.exe", "pimpleFoam"], runtime=Path(tempfile.mkdtemp()),
            publish_motion=lambda identity: None, wait_consumed=lambda identity: None,
            read_force=lambda identity: {"force_y_N": 1.0}, launcher=launcher)
        engine.start(); identity = StepIdentity.create(run_id="r", case_id="c", source_global_step=559, source_time_s=2.2075,
            source_tick=2207500000, global_step=560, time_s=2.20875, dt_s=.00125)
        result = engine.advance(identity); self.assertEqual(result.return_code, 0)
        with self.assertRaises(CoordinatorError): engine.start()
        engine.stop(); self.assertEqual(engine.start_count, 1); self.assertEqual(engine.owned_residual, 0)


if __name__ == "__main__": unittest.main()
