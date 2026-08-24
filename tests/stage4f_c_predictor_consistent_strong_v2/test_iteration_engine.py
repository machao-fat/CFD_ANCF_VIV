from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.coupling.stage4f_c_predictor_consistent_strong_v2 import iteration_engine as module


class _Runner:
    def __init__(self, state):
        self.state = state

    def state_view(self):
        return self.state

    def save_checkpoint(self, path):
        Path(path).write_bytes(b"predictor-native-state")


class _Adapter:
    def __init__(self, runner):
        self.runner = runner
        self.state_provider = runner.state_view
        self.predict_calls = 0
        self.discard_calls = 0

    def predict_all(self, *_args):
        self.predict_calls += 1
        return [SimpleNamespace(to_dict=lambda: {"slice_id": 0, "motion": "predictor"})]

    def discard_staged(self):
        self.discard_calls += 1
        self.runner.state = {"q": [1.0], "qdot": [2.0], "qddot": [3.0]}


class _CheckpointManager:
    def __init__(self, root):
        self.root = root
        self.prepared_state = None
        self.native_bytes = None

    def prepare(self, **kwargs):
        structure = kwargs["structure"]
        self.prepared_state = structure.export_staged_checkpoint()
        native = self.root / "exported_predictor.mat"
        structure.export_runner_checkpoint(native)
        self.native_bytes = native.read_bytes()
        return SimpleNamespace(staged_token="predictor-token")

    def commit(self, _prepared):
        path = self.root / "checkpoint.json"
        path.write_text("predictor-checkpoint", encoding="utf-8")
        return path


class PredictorConsistentEngineTests(unittest.TestCase):
    def _engine(self, root):
        engine = object.__new__(module.CandidateIterationEngine)
        engine.root = root
        engine.physical_step = 4
        engine.target_time_s = 1.508125
        engine._predictor_snapshot = None
        engine._predictor_restored_for_promotion = False
        runner = _Runner({"q": [1.0], "qdot": [2.0], "qddot": [3.0]})
        engine.runner = runner
        engine.adapter = _Adapter(runner)
        return engine

    def test_predictor_snapshot_writes_native_json_and_coherence_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = self._engine(root)
            rows = [{"slice_id": 0, "motion": "predictor"}]
            engine._motion_rows_from_state = lambda _state: rows
            engine._capture_predictor_snapshot([SimpleNamespace(to_dict=lambda: rows[0])])

            snapshot = engine._predictor_snapshot
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertTrue(Path(snapshot["native_path"]).is_file())
            self.assertTrue(Path(snapshot["json_path"]).is_file())
            audit = json.loads(Path(snapshot["audit_path"]).read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "passed")
            self.assertTrue(audit["mixed_predictor_cfd_corrector_forbidden"])
            self.assertEqual(audit["cfd_motion_state_role"], "predictor_snapshot")

    def test_predictor_snapshot_rejects_motion_from_a_different_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = self._engine(Path(temporary))
            engine._motion_rows_from_state = lambda _state: [{"slice_id": 0, "motion": "different"}]
            with self.assertRaisesRegex(module.PredictorSnapshotError, "not generated"):
                engine._capture_predictor_snapshot([
                    SimpleNamespace(to_dict=lambda: {"slice_id": 0, "motion": "predictor"})
                ])

    def test_trial_retains_corrector_for_diagnostics_and_marks_predictor_as_promotion_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = self._engine(Path(temporary))

            def capture(_rows):
                engine._predictor_snapshot = {
                    "json_path": "predictor.json", "native_path": "predictor.mat",
                    "state_sha256": "a" * 64, "native_sha256": "b" * 64,
                    "published_motion_sha256": "c" * 64,
                    "audit": {"status": "passed", "mixed_predictor_cfd_corrector_forbidden": True},
                }

            engine._capture_predictor_snapshot = capture

            def inherited_run_trial(self, **_kwargs):
                self.adapter.predict_all(4, 1.508125, [[0.0, 0.0, 0.0]] * 3)
                self._trial = {
                    "geometry_audit": [{"slice_id": 0, "position_gap_over_D": 0.2}],
                    "position_difference_over_D": 0.2,
                    "velocity_difference_over_U": 0.3,
                    "observed_slice_forces_N": [[1.0, 0.0, 0.0]] * 3,
                    "generalized_force_N": [1.0],
                }
                return dict(self._trial)

            with patch.object(module.v1.CandidateIterationEngine, "run_trial", inherited_run_trial):
                result = engine.run_trial(previous_slice_forces_N=[[0.0, 0.0, 0.0]] * 3)

            self.assertEqual(engine.adapter.predict_calls, 1)
            self.assertNotIn("geometry_audit", result)
            self.assertEqual(result["state_role"], "predictor_snapshot_for_cfd_and_promotion")
            self.assertEqual(result["geometry_state_role"], "corrector_diagnostic_only")
            self.assertEqual(result["corrector_diagnostics"]["position_difference_over_D"], 0.2)
            self.assertTrue(result["mixed_predictor_cfd_corrector_forbidden"])

    def test_promotion_restores_and_exports_predictor_but_persists_actual_observed_loads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = self._engine(root)
            native = root / "predictor.mat"
            native.write_bytes(b"predictor-native-state")
            audit_path = root / "state_coherence_audit.json"
            module.atomic_write_json(audit_path, {"status": "passed"})
            state = {"q": [1.0], "qdot": [2.0], "qddot": [3.0]}
            engine._predictor_snapshot = {
                "state": state, "state_sha256": module._canonical_sha256(state),
                "native_path": str(native), "native_sha256": module.sha256_file(native),
                "audit": {"status": "passed"}, "audit_path": str(audit_path),
            }
            manager = _CheckpointManager(root)
            engine._trial = {
                "observed_slice_forces_N": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],
                "generalized_force_N": [10.0],
            }
            engine._trial_discarded = False
            engine._promoted_checkpoint = None
            engine.scheduler = SimpleNamespace(
                state=module.v1.SchedulerState.STRUCTURE_CORRECTED,
                checkpoint_manager=manager, processes={0: object(), 1: object(), 2: object()},
                _active_checkpoint=None, _active_correction={"corrector": True},
                last_committed_step=3, last_committed_time_s=1.5075,
                previous_slice_forces_N=[[999.0, 999.0, 999.0]] * 3,
                previous_generalized_force=[999.0],
            )
            engine.scheduler._transition = lambda state, **_kwargs: setattr(engine.scheduler, "state", state)

            checkpoint = engine.promote()

            self.assertTrue(checkpoint.is_file())
            self.assertEqual(engine.adapter.discard_calls, 1)
            self.assertEqual(manager.prepared_state["q"], [1.0])
            self.assertEqual(manager.native_bytes, b"predictor-native-state")
            self.assertEqual(engine.scheduler.previous_slice_forces_N, engine._trial["observed_slice_forces_N"])
            self.assertNotEqual(engine.scheduler.previous_slice_forces_N, [[999.0, 999.0, 999.0]] * 3)
            self.assertEqual(engine.scheduler.state, module.v1.SchedulerState.COMMITTED)
            self.assertTrue(engine._trial["observed_force_persisted"])


if __name__ == "__main__":
    unittest.main()
