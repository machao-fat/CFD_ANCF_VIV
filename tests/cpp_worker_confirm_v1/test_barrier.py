from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.barrier import Stage100SliceBarrier
from coupling.performance_optimization_v2.coordinator import SliceResult, canonical_hash


class Engine:
    def __init__(self, sid, _path):
        self.slice_id, self.starts, self.stops = int(sid), 0, 0

    def start(self): self.starts += 1

    def advance(self, identity, motion):
        payload = {"slice_id": self.slice_id, "motion_step": motion["global_step"], "ack": "consumed"}
        return SliceResult(self.slice_id, identity, payload, canonical_hash(payload), 0, 5000 + self.slice_id, 0.0)

    def stop(self): self.stops += 1

    def rollback_step(self, identity):
        self.rollback_calls = getattr(self, "rollback_calls", 0) + 1

    @property
    def owned_residual(self): return 0


class BarrierTests(unittest.TestCase):
    def test_three_slice_barrier_commits_after_all(self):
        engines = {}

        def factory(sid, path):
            engines[sid] = Engine(sid, path)
            return engines[sid]

        barrier = Stage100SliceBarrier(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, dt_s=.00125,
            runtime=Path(tempfile.mkdtemp()), engine_factory=factory)
        barrier.start()
        record = barrier.advance_step(global_step=560, time_s=2.20875,
            motion_by_slice={sid: {"global_step": 560} for sid in range(3)})
        self.assertEqual(record["slice_ids"], [0, 1, 2])
        self.assertTrue(record["committed"])
        barrier.stop()
        self.assertEqual(barrier.owned_residual, 0)

    def test_prepare_does_not_commit_until_explicit_commit(self):
        engines = {}
        def factory(sid, _path):
            engines[sid] = Engine(sid, _path)
            return engines[sid]
        barrier = Stage100SliceBarrier(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, dt_s=.00125,
            runtime=Path(tempfile.mkdtemp()), engine_factory=factory)
        barrier.start()
        prepared = barrier.prepare_step(global_step=560, time_s=2.20875,
            motion_by_slice={sid: {"global_step": 560} for sid in range(3)})
        self.assertTrue(prepared["prepared"])
        self.assertFalse(prepared["committed"])
        self.assertEqual(barrier.records, [])
        self.assertEqual([item.slice_id for item in barrier.prepared_results], [0, 1, 2])
        committed = barrier.commit_prepared(worker_response={"sequence": 2})
        self.assertTrue(committed["committed"])
        self.assertEqual(len(barrier.records), 1)
        barrier.stop()

    def test_commit_callback_failure_leaves_no_visible_checkpoint(self):
        barrier = Stage100SliceBarrier(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, dt_s=.00125,
            runtime=Path(tempfile.mkdtemp()), engine_factory=Engine)
        barrier.start()
        barrier.prepare_step(global_step=560, time_s=2.20875,
            motion_by_slice={sid: {"global_step": 560} for sid in range(3)})
        with self.assertRaises(Exception):
            barrier.commit_prepared(commit_callback=lambda: (_ for _ in ()).throw(RuntimeError("adapter commit failed")))
        self.assertTrue(barrier.failed)
        self.assertEqual(barrier.records, [])
        self.assertFalse((barrier.runtime / "checkpoint" / "checkpoint_00000560.json").exists())
        self.assertEqual([barrier.engines[sid].rollback_calls for sid in range(3)], [1, 1, 1])
        journal = json.loads((barrier.runtime / "commit_journal" / "commit_00000560.json").read_text(encoding="utf-8"))
        self.assertEqual(journal["state"], "aborted")
        self.assertEqual(journal["recovery"], "runtime_terminal_no_resume")
        barrier.stop()

    def test_commit_failure_invokes_rollback_callback(self):
        barrier = Stage100SliceBarrier(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, dt_s=.00125,
            runtime=Path(tempfile.mkdtemp()), engine_factory=Engine)
        barrier.start()
        barrier.prepare_step(global_step=560, time_s=2.20875,
            motion_by_slice={sid: {"global_step": 560} for sid in range(3)})
        calls = []
        with self.assertRaises(Exception):
            barrier.commit_prepared(
                commit_callback=lambda: (_ for _ in ()).throw(RuntimeError("commit failed")),
                rollback_callback=lambda: calls.append("rollback"),
            )
        self.assertEqual(calls, ["rollback"])
        barrier.stop()

    def test_missing_slice_motion_poisoned(self):
        barrier = Stage100SliceBarrier(run_id="run", case_id="case", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, dt_s=.00125,
            runtime=Path(tempfile.mkdtemp()), engine_factory=Engine)
        barrier.start()
        with self.assertRaises(Exception):
            barrier.advance_step(global_step=560, time_s=2.20875, motion_by_slice={0: {}})
        self.assertTrue(barrier.failed)
        barrier.stop()


if __name__ == "__main__": unittest.main()
