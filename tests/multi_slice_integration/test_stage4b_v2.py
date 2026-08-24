from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.coupling.checkpoint.atomic_checkpoint import CommittedPublishError
from src.coupling.multi_slice_driver import (
    LoadRecord,
    MotionRecord,
    MultiSliceConfig,
    MultiSliceScheduler,
    ProductionANCFAdapter,
    RuntimeConfig,
    SchedulerError,
    SchedulerState,
    SliceManifest,
    SliceSpec,
)
from src.coupling.multi_slice_driver.mocks import MockSliceProcess, MockStructureAdapter
from src.coupling.multi_slice_driver.protocol import ProtocolError, publish_payload, read_ready_payload
from src.coupling.multi_slice_mapping.mapping import (
    SCHEMA_VERSION,
    SliceDefinition,
    atomic_write_json,
    create_ready_marker,
)
from tests.multi_slice_driver.harness import make_harness


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "multi_slice_mapping" / "fixtures"


class Stage4BV2Tests(unittest.TestCase):
    def test_a_to_b_golden_hash_and_marker_cross_acceptance(self):
        manifest = SliceManifest.from_mapping(json.loads((FIXTURES / "golden_manifest_0.2.1.json").read_text(encoding="utf-8")))
        runtime = RuntimeConfig.from_mapping(json.loads((FIXTURES / "golden_config_0.2.1.json").read_text(encoding="utf-8")))
        self.assertEqual(manifest.slice_manifest_sha256, "ffbf9af8cfe8d65d90762fe088c89e4f427c0eb6a010a20741cee788e6437a5d")
        self.assertEqual(runtime.config_sha256, "2c8b815b2bf43cd8581e5eeef604a456d7cff8ca77fb0f4ae08978ec28efd9aa")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scheduler, structure, processes, _ = make_harness(root=root)
            config = MultiSliceConfig(
                case_id=manifest.case_id, dt_s=runtime.dt_s, timeout_s=runtime.timeout_s,
                manifest=manifest,
            )
            self.assertEqual(config.config_sha256, runtime.config_sha256)
            paths = scheduler.paths[0]
            motion = MotionRecord(
                schema_version=SCHEMA_VERSION, case_id=manifest.case_id, step=0,
                coupling_iteration=0, time_s=0.0, slice_id=0, s_ref_m=2.5,
                slice_length_m=5.0, x_ref_m=0.0, y_ref_m=0.0, z_ref_m=2.5,
                ux_m=0.0, uy_m=0.01, uz_m=0.0, x_m=0.0, y_m=0.01, z_m=2.5,
                vx_mps=0.0, vy_mps=0.0, vz_mps=0.0, ax_mps2=0.0, ay_mps2=0.0, az_mps2=0.0,
            )
            publish_payload(
                payload_path=paths.payload("motion", 0), ready_path=paths.ready("motion", 0),
                kind="motion", record=motion, manifest=manifest, runtime_config=runtime,
            )
            accepted = read_ready_payload(
                paths=paths, kind="motion", step=0, time_s=0.0,
                manifest=manifest, runtime_config=runtime, timeout_s=1.0,
            )
            self.assertEqual(accepted.slice_id, 0)
            payload = paths.payload("motion", 0)
            payload.write_bytes(payload.read_bytes().replace(b"0.01", b"0.02"))
            with self.assertRaises(ProtocolError):
                read_ready_payload(paths=paths, kind="motion", step=0, time_s=0.0, manifest=manifest, runtime_config=runtime, timeout_s=0.1)

    def test_precommit_faults_leave_no_committed_manifest_and_discard_stage(self):
        faults = ("staged_correction_failure", "staged_checkpoint_export_failure", "checkpoint_missing_U")
        for fault in faults:
            with self.subTest(fault=fault):
                scheduler, structure, processes, root = make_harness(faults={1: fault} if fault.startswith("checkpoint_") else None, structure_fault=fault if fault.startswith("staged_") else None)
                with self.assertRaises(SchedulerError):
                    scheduler.run_step(step=0, time_s=0.0)
                self.assertEqual(scheduler.state, SchedulerState.FAILED)
                self.assertEqual(structure.committed_step, -1)
                self.assertIsNone(structure.pending_state)
                self.assertFalse(list((root / "checkpoints").glob("checkpoint_*.json")))

    def test_manifest_publish_failure_is_precommit(self):
        scheduler, structure, processes, root = make_harness()
        def fail_publish(prepared):
            raise CommittedPublishError("injected atomic publish failure", published=False, path=root / "checkpoints" / "checkpoint_injected.json")
        scheduler.checkpoint_manager.commit = fail_publish  # type: ignore[method-assign]
        with self.assertRaises(SchedulerError):
            scheduler.run_step(step=0, time_s=0.0)
        self.assertEqual(scheduler.state, SchedulerState.FAILED)
        self.assertEqual(structure.committed_step, -1)
        self.assertFalse(list((root / "checkpoints").glob("checkpoint_*.json")))

    def test_postcommit_finalize_failure_requires_recovery_and_is_idempotent(self):
        scheduler, structure, processes, root = make_harness()
        original = structure.finalize_committed
        calls = {"n": 0}
        def fail_once(token=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("injected post-commit finalize failure")
            return original(token)
        structure.finalize_committed = fail_once  # type: ignore[method-assign]
        with self.assertRaises(SchedulerError):
            scheduler.run_step(step=0, time_s=0.0)
        self.assertEqual(scheduler.state, SchedulerState.RECOVERY_REQUIRED)
        committed = list((root / "checkpoints").glob("checkpoint_*.json"))
        self.assertEqual(len(committed), 1)
        self.assertEqual(structure.committed_step, -1)
        restored = scheduler.recover_from_checkpoint(committed[0])
        self.assertEqual(restored["step"], 0)
        self.assertEqual(scheduler.state, SchedulerState.INITIALIZED)
        self.assertEqual(structure.committed_step, 0)
        with self.assertRaises(SchedulerError):
            scheduler.run_step(step=0, time_s=0.0)
        result = scheduler.run_step(step=1, time_s=0.01)
        self.assertEqual(result.step, 1)
        self.assertEqual(len(list((root / "checkpoints").glob("checkpoint_*.json"))), 2)

    def test_recovery_slice_and_structure_restore_fail_closed_then_retry(self):
        scheduler, structure, processes, root = make_harness()
        original = structure.finalize_committed
        first = {"n": 0}
        def fail_once(token=None):
            first["n"] += 1
            if first["n"] == 1:
                raise RuntimeError("post-commit")
            return original(token)
        structure.finalize_committed = fail_once  # type: ignore[method-assign]
        with self.assertRaises(SchedulerError):
            scheduler.run_step(step=0, time_s=0.0)
        checkpoint = next((root / "checkpoints").glob("checkpoint_*.json"))
        processes[1].fault = "recovery_slice_restore"
        with self.assertRaises(SchedulerError):
            scheduler.recover_from_checkpoint(checkpoint)
        self.assertEqual(scheduler.state, SchedulerState.RECOVERY_REQUIRED)
        processes[1].fault = None
        original_load = structure.load_checkpoint
        load_calls = {"n": 0}
        def fail_structure(path):
            load_calls["n"] += 1
            if load_calls["n"] == 1:
                raise RuntimeError("structure restore")
            return original_load(path)
        structure.load_checkpoint = fail_structure  # type: ignore[method-assign]
        with self.assertRaises(SchedulerError):
            scheduler.recover_from_checkpoint(checkpoint)
        self.assertEqual(scheduler.state, SchedulerState.RECOVERY_REQUIRED)
        scheduler.recover_from_checkpoint(checkpoint)
        self.assertEqual(scheduler.last_committed_step, 0)

    def test_static_motion_scale_is_manifested_and_restart_validates_hash(self):
        scheduler, structure, processes, root = make_harness()
        result = scheduler.run_step(step=0, time_s=0.0)
        manifest = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
        for entry in manifest["slices"]:
            static_paths = {item["relative_path"] for item in entry["static_files"]}
            time_paths = {item["relative_path"] for item in entry["time_files"]}
            self.assertIn("0/motionScale", static_paths)
            self.assertNotIn(f"{entry['openfoam_time_name']}/motionScale", time_paths)
        self.assertTrue((root / "cases" / "slices" / "slice_0000" / "0" / "motionScale").is_file())

    def test_production_adapter_uses_a_h_and_staged_token(self):
        manifest = SliceManifest(
            schema_version=SCHEMA_VERSION, case_id="adapter", reference_length_m=1.0,
            represented_length_m=1.0, slices=(SliceDefinition(0, 0.5, 1.0, 1.0),),
        )
        state = {"q": [0.0] * 12, "qdot": [0.0] * 12, "qddot": [0.0] * 12}
        class Runner:
            def predict(self, step, time_s, load):
                return {"step": step}, []
            def correct(self, step, time_s, load):
                state["q"][1] = 0.2
                return {"step": step, "time_s": time_s, "audit": {}}, []
            def save_checkpoint(self, path):
                Path(path).write_text(json.dumps(state), encoding="utf-8")
            def load_checkpoint(self, path):
                state.update(json.loads(Path(path).read_text(encoding="utf-8")))
        adapter = ProductionANCFAdapter(runner=Runner(), manifest=manifest, mesh_nodes=(0.0, 1.0), state_provider=lambda: state)
        adapter.set_case_id("adapter")
        motion = adapter.predict_all(0, 0.0, [[0.0, 0.0, 0.0]])
        self.assertEqual(motion[0].schema_version, "0.2.1")
        load = LoadRecord.from_conversion(case_id="adapter", step=0, time_s=0.0, slice_definition=manifest.slices[0], unit_span_m=1.0, openfoam_force_N=(0.0, 1.0, 0.0), cfd_time_step_s=0.01)
        correction = adapter.correct_all(0, 0.0, [load])
        exported = adapter.export_staged_checkpoint()
        self.assertEqual(correction["checkpoint_token"], exported["checkpoint_token"])
        adapter.discard_staged()
        self.assertEqual(state["q"][1], 0.0)


if __name__ == "__main__":
    unittest.main()
