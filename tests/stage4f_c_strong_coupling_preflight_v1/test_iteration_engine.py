from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.coupling.stage4f_c_strong_coupling_preflight_v1 import iteration_engine as engine_module


class _Record:
    def __init__(self, row):
        self.force_N = tuple(row["force"])


class _Adapter:
    def __init__(self):
        self.finalized = []
        self.discarded = 0

    def finalize_committed(self, token):
        self.finalized.append(token)

    def discard_staged(self):
        self.discarded += 1


class _CheckpointManager:
    def __init__(self, root: Path):
        self.root = root
        self.prepare_calls = []
        self.commit_calls = []

    def prepare(self, **kwargs):
        self.prepare_calls.append(kwargs)
        return SimpleNamespace(staged_token="actual-observed-token")

    def commit(self, prepared):
        self.commit_calls.append(prepared)
        result = self.root / "checkpoint_actual.json"
        result.write_text("actual", encoding="utf-8")
        return result


class _Process:
    def __init__(self):
        self.finished = 0

    def finish_step(self, step, time_s):
        self.finished += 1


class _TrialProcess:
    def __init__(self, slice_id):
        self.slice_id = slice_id
        self.case = Path(f"slice_{slice_id}")
        self.log_paths = [f"slice_{slice_id}.log"]
        self.calls = []

    def begin_step(self, _seed, *, seed_step):
        self.calls.append("begin_step")

    def publish_motion(self, record, *args, **kwargs):
        self.calls.append("publish_motion")
        return {"payload_sha256": "m"}

    def wait_motion_consumed(self, *args, **kwargs):
        self.calls.append("wait_motion_consumed")
        return {"payload_sha256": "mc"}

    def advance_one_step(self, *args):
        self.calls.append("advance_one_step")

    def wait_load_ready(self, *args, **kwargs):
        self.calls.append("wait_load_ready")
        return {"payload_sha256": "l"}

    def read_load(self, *args):
        self.calls.append("read_load")
        return _TrialLoad(self.slice_id)

    def publish_load_consumed(self, *args, **kwargs):
        self.calls.append("publish_load_consumed")
        return {"payload_sha256": "lc"}

    def return_code(self):
        return 0

    def finish_step(self, *args):
        self.calls.append("finish_step")


class _TrialLoad:
    def __init__(self, slice_id):
        self.slice_id = slice_id
        self.force_N = (slice_id + 1.0, 0.0, 0.0)

    def to_dict(self):
        return {"slice_id": self.slice_id, "force": list(self.force_N)}


class _TrialAdapter:
    H_by_slice_id = {0: ((1.0,),), 1: ((1.0,),), 2: ((1.0,),)}

    def __init__(self):
        self.corrected = None
        self.accepted = None

    def predict_all(self, step, time_s, previous):
        return [_TrialMotion(item) for item in range(3)]

    def accept_generalized_force(self, value):
        self.accepted = list(value)

    def correct_all(self, step, time_s, loads):
        self.corrected = list(loads)
        return {"step": step, "time_s": time_s, "generalized_force": [4.0], "checkpoint_token": "trial"}

    def export_staged_checkpoint(self):
        return {"q": [1.0], "qdot": [0.0], "qddot": [0.0], "checkpoint_token": "trial"}


class _TrialMotion:
    def __init__(self, slice_id):
        self.slice_id = slice_id


class CandidatePromotionTests(unittest.TestCase):
    def _engine(self, root: Path):
        candidate = object.__new__(engine_module.CandidateIterationEngine)
        candidate._trial_discarded = False
        candidate._promoted_checkpoint = None
        candidate.physical_step = 7
        candidate.target_time_s = 1.508125
        candidate.root = root
        candidate.manifest = SimpleNamespace(R_GL=((1.0, 0.0, 0.0),) * 3)
        candidate.adapter = _Adapter()
        candidate._snapshot_processes = lambda: None
        candidate._finish_slice_processes = lambda: None
        manager = _CheckpointManager(root)
        candidate.scheduler = SimpleNamespace(
            state=engine_module.SchedulerState.STRUCTURE_CORRECTED,
            checkpoint_manager=manager,
            processes={0: object(), 1: object(), 2: object()},
            _active_checkpoint=None,
            _active_correction={"step": 7},
            last_committed_step=6,
            last_committed_time_s=1.5075,
            previous_slice_forces_N=[[999.0, 999.0, 999.0]] * 3,
            previous_generalized_force=[999.0],
        )
        candidate.scheduler._transition = lambda state, **_: setattr(candidate.scheduler, "state", state)
        candidate._trial = {
            "integrated_slice_forces": [
                {"force": [1.0, 2.0, 3.0]},
                {"force": [4.0, 5.0, 6.0]},
                {"force": [7.0, 8.0, 9.0]},
            ],
            "observed_slice_forces_N": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],
            "generalized_force_N": [10.0, 11.0],
        }
        return candidate, manager

    def test_trial_method_has_no_checkpoint_manager_reference(self):
        source = inspect.getsource(engine_module.CandidateIterationEngine.run_trial)
        self.assertNotIn("checkpoint_manager", source)
        self.assertNotIn("finalize_committed", source)
        self.assertIn("correct_all", source)

    def test_promote_persists_observed_not_relaxed_guess_and_only_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manager = self._engine(root)
            with patch.object(engine_module, "LoadRecord", SimpleNamespace(from_mapping=lambda row, _: _Record(row))):
                with patch.object(engine_module, "sha256_file", return_value="a" * 64):
                    path = candidate.promote()
            self.assertTrue(path.is_file())
            self.assertEqual(len(manager.prepare_calls), 1)
            self.assertEqual(len(manager.commit_calls), 1)
            self.assertEqual(
                manager.prepare_calls[0]["previous_slice_forces_N"],
                [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],
            )
            self.assertNotEqual(manager.prepare_calls[0]["previous_slice_forces_N"], [[999.0, 999.0, 999.0]] * 3)
            self.assertEqual(candidate.adapter.finalized, ["actual-observed-token"])
            self.assertEqual(candidate.scheduler.state, engine_module.SchedulerState.COMMITTED)
            self.assertTrue(candidate._trial["observed_force_persisted"])
            with self.assertRaisesRegex(RuntimeError, "already been promoted"):
                candidate.promote()

    def test_discard_never_prepares_and_marks_staged_state_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manager = self._engine(root)
            candidate._finish_slice_processes = lambda: None
            candidate.discard_trial()
            self.assertEqual(candidate.adapter.discarded, 1)
            self.assertTrue(candidate._trial_discarded)
            self.assertTrue(candidate._trial["staged_correction_discarded"])
            self.assertEqual(manager.prepare_calls, [])
            with self.assertRaisesRegex(RuntimeError, "undiscarded"):
                candidate.promote()

    def test_promotion_requires_staged_correction(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate, manager = self._engine(Path(temporary))
            candidate.scheduler.state = engine_module.SchedulerState.CFD_ADVANCED
            with self.assertRaisesRegex(RuntimeError, "staged-correction"):
                candidate.promote()
            self.assertEqual(manager.prepare_calls, [])

    def test_complete_trial_transaction_never_prepares_or_commits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent.json"
            parent.write_text("parent", encoding="utf-8")
            candidate = object.__new__(engine_module.CandidateIterationEngine)
            candidate.closed = False
            candidate._trial = None
            candidate._trial_discarded = False
            candidate._promoted_checkpoint = None
            candidate.physical_step = 2
            candidate.current_time_s = 1.5075
            candidate.target_time_s = 1.508125
            candidate.root = root
            candidate.parent_checkpoint = parent
            candidate.manifest = SimpleNamespace(
                slices=tuple(SimpleNamespace(slice_id=item) for item in range(3)),
                R_GL=((1.0, 0.0, 0.0),) * 3,
            )
            candidate.adapter = _TrialAdapter()
            processes = {item: _TrialProcess(item) for item in range(3)}
            manager = _CheckpointManager(root)
            candidate.scheduler = SimpleNamespace(
                state=engine_module.SchedulerState.INITIALIZED,
                last_committed_step=1,
                previous_slice_forces_N=[[0.0, 0.0, 0.0]] * 3,
                previous_generalized_force=[],
                processes=processes,
                paths={item: object() for item in range(3)},
                config=SimpleNamespace(runtime_config=object()),
                checkpoint_manager=manager,
                _active_correction=None,
            )
            candidate.scheduler._h_by_slice_id = lambda: candidate.adapter.H_by_slice_id
            candidate.scheduler._transition = lambda state, **_: setattr(candidate.scheduler, "state", state)
            candidate.scheduler._append_log = lambda **_: None
            candidate._stamp_closed_matlab = lambda: None
            candidate._snapshot_processes = lambda: None
            candidate.processes = list(processes.values())
            candidate.runner = object()

            class _Mapping:
                generalized_force = [3.0]
                virtual_work = SimpleNamespace(to_dict=lambda: {"error_rel": 0.0})

            def transaction(rows, *_args, **_kwargs):
                return {row.slice_id: row for row in rows}

            with patch.object(engine_module.r2, "_seed_records", return_value=[{}, {}, {}]), \
                 patch.object(engine_module, "MotionRecord", _TrialMotion), \
                 patch.object(engine_module, "LoadRecord", _TrialLoad), \
                 patch.object(engine_module, "validate_record_transaction", side_effect=transaction), \
                 patch.object(engine_module, "map_integrated_slice_forces", return_value=_Mapping()), \
                 patch.object(engine_module.r2, "_force_audit", return_value={"Cd": 1.0, "max_relative_error": 0.0}), \
                 patch.object(engine_module.r2, "_motion_csv", return_value={"x_m": 0.0, "y_m": 0.0, "vx_mps": 0.0, "vy_mps": 0.0}), \
                 patch.object(engine_module.r2, "cylinder_center", return_value=[0.0, 0.0, 0.0]), \
                 patch.object(engine_module.r2, "_state_motion", return_value={"x_m": 0.0, "y_m": 0.0, "vx_mps": 0.0, "vy_mps": 0.0}), \
                 patch.object(engine_module.r2, "_log_audit", return_value={"max_cfl": 0.1, "passed": True}), \
                 patch.object(engine_module, "sha256_file", return_value="b" * 64):
                result = candidate.run_trial(previous_slice_forces_N=[[9.0, 0.0, 0.0]] * 3)

            self.assertEqual(manager.prepare_calls, [])
            self.assertEqual(manager.commit_calls, [])
            self.assertFalse(result["formal_checkpoint_created"])
            self.assertEqual(result["observed_slice_forces_N"], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
            self.assertEqual(candidate.scheduler.state, engine_module.SchedulerState.STRUCTURE_CORRECTED)
            for process in processes.values():
                self.assertEqual(process.calls, ["begin_step", "publish_motion", "wait_motion_consumed", "advance_one_step", "wait_load_ready", "read_load", "publish_load_consumed", "finish_step"])


if __name__ == "__main__":
    unittest.main()
