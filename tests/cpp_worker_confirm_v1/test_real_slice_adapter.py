from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from coupling.cpp_worker_confirm_v1.real_slice_adapter import PersistentOpenFOAMSliceAdapter, RealSliceAdapterError
from coupling.multi_slice_driver.contract import SliceExchangePaths, SliceSpec, build_config, build_slice_manifest
from coupling.multi_slice_mapping.mapping import LoadRecord, MotionRecord, RuntimeConfig, SliceManifest
from coupling.performance_optimization_v2.coordinator import StepIdentity


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.process = SimpleNamespace(pid=9001, poll=lambda: None)
        self.owned_residual = 0

    def begin_step(self, seed, *, seed_step): self.calls.append(("begin_step", seed_step))
    def publish_motion(self, record, paths, *, manifest, runtime_config): self.calls.append(("publish_motion", record.step))
    def wait_motion_consumed(self, step, time_s, *, paths, manifest, runtime_config): self.calls.append(("motion_ack", step))
    def advance_one_step(self, step, time_s): self.calls.append(("advance", step))
    def wait_load_ready(self, step, time_s, *, paths, manifest, runtime_config): self.calls.append(("force_ready", step))
    def read_load(self, step, time_s):
        self.calls.append(("read_load", step))
        return LoadRecord.from_conversion(case_id="case", step=step, time_s=time_s,
            slice_definition=SliceSpec(0, 1.0, 1.0), unit_span_m=1.0,
            openfoam_force_N=(1.0, 2.0, 0.0), cfd_time_step_s=0.00125)
    def publish_load_consumed(self, step, time_s, *, paths, manifest, runtime_config): self.calls.append(("load_ack", step))
    def finish_step(self, step, time_s): self.calls.append(("finish", step))
    def stop(self): self.calls.append(("stop",))


def motion(step: int, time_s: float) -> MotionRecord:
    return MotionRecord(schema_version="0.2.1", case_id="case", step=step, coupling_iteration=0,
        time_s=time_s, slice_id=0, s_ref_m=1.0, slice_length_m=1.0,
        x_ref_m=0.0, y_ref_m=0.0, z_ref_m=1.0, ux_m=0.0, uy_m=0.0, uz_m=0.0,
        x_m=0.0, y_m=0.0, z_m=1.0, vx_mps=0.0, vy_mps=0.0, vz_mps=0.0,
        ax_mps2=0.0, ay_mps2=0.0, az_mps2=0.0)


class RealSliceAdapterTests(unittest.TestCase):
    def make(self):
        manifest = SliceManifest.from_mapping(build_slice_manifest("case", [SliceSpec(0, 1.0, 1.0)]))
        config = RuntimeConfig.from_mapping(build_config(case_id="case", dt_s=0.00125, timeout_s=1.0,
            specs=[SliceSpec(0, 1.0, 1.0)], start_time_s=2.2075))
        root = Path(tempfile.mkdtemp())
        backend = FakeBackend()
        adapter = PersistentOpenFOAMSliceAdapter(backend=backend, manifest=manifest, runtime_config=config,
            paths=SliceExchangePaths(root / "exchange", manifest.slices[0]), initial_seed=motion(559, 2.2075), slice_id=0)
        return adapter, backend

    def test_existing_backend_lifecycle_is_adapted_without_starting_at_import(self):
        adapter, backend = self.make(); adapter.start()
        identity = StepIdentity.create(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, global_step=560,
            time_s=2.20875, dt_s=0.00125)
        result = adapter.advance(identity, motion(560, 2.20875))
        self.assertEqual(result.return_code, 0)
        adapter.finalize_step(identity); adapter.stop()
        self.assertEqual(adapter.start_count, 1)
        self.assertIn(("finish", 560), backend.calls)
        self.assertIn(("stop",), backend.calls)

    def test_motion_record_seed_is_serialized_for_existing_backend(self):
        class MappingSeedBackend(FakeBackend):
            def begin_step(self, seed, *, seed_step):
                self.calls.append(("begin_step_type", type(seed).__name__, seed_step))
                if not isinstance(seed, dict):
                    raise TypeError("seed must be a mapping")

        manifest = SliceManifest.from_mapping(build_slice_manifest("case", [SliceSpec(0, 1.0, 1.0)]))
        config = RuntimeConfig.from_mapping(build_config(case_id="case", dt_s=0.00125, timeout_s=1.0,
            specs=[SliceSpec(0, 1.0, 1.0)], start_time_s=2.2075))
        root = Path(tempfile.mkdtemp())
        backend = MappingSeedBackend()
        adapter = PersistentOpenFOAMSliceAdapter(
            backend=backend, manifest=manifest, runtime_config=config,
            paths=SliceExchangePaths(root / "exchange", manifest.slices[0]),
            initial_seed=motion(559, 2.2075), slice_id=0)
        adapter.start()
        identity = StepIdentity.create(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, global_step=560,
            time_s=2.20875, dt_s=0.00125)
        adapter.advance(identity, motion(560, 2.20875))
        self.assertEqual(backend.calls[0], ("begin_step_type", "dict", 559))
        adapter.stop()

    def test_motion_is_required_and_failure_is_terminal(self):
        adapter, _backend = self.make(); adapter.start()
        identity = StepIdentity.create(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, global_step=560,
            time_s=2.20875, dt_s=0.00125)
        with self.assertRaises(RealSliceAdapterError): adapter.advance(identity)
        with self.assertRaises(RealSliceAdapterError): adapter.advance(identity, motion(560, 2.20875))
        adapter.stop()


if __name__ == "__main__": unittest.main()
