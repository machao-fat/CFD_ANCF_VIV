from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_to70s_rollover_v1.retention import (
    RetentionError,
    RetentionPolicy,
    RollingRetentionStore,
)


class RollingRetentionTests(unittest.TestCase):
    def _store(self, root: Path, *, keep: int = 3, min_free: int = 0) -> RollingRetentionStore:
        return RollingRetentionStore(
            runtime=root / "runtime", results=root / "results", run_id="run219",
            case_id="case219", policy=RetentionPolicy(
                source_step=0, source_time_s=0.0, dt_s=0.00125,
                keep_full_steps=keep, keep_restart_checkpoints=2,
                min_free_bytes=min_free,
            ),
        )

    @staticmethod
    def _checkpoint(step: int) -> dict:
        return {
            "run_id": "run219", "case_id": "case219", "global_step": step,
            "time_s": step * 0.00125, "integer_tick": step * 1_250_000,
            "committed": True, "state": {"q": [float(step)], "qdot": [0.0], "qddot": [0.0]},
        }

    @staticmethod
    def _row(step: int) -> dict:
        return {
            "run_id": "run219", "case_id": "case219", "global_step": step,
            "time_s": step * 0.00125, "integer_tick": step * 1_250_000,
            "committed": True,
        }

    def _materialize_step(self, store: RollingRetentionStore, step: int) -> None:
        time_name = format(step * 0.00125, ".12g")
        for sid in range(3):
            directory = store.runtime / "cases" / f"slice_{sid:04d}" / time_name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "U").write_text(f"step={step}\n", encoding="utf-8")
        commit = store.runtime / "commit_journal" / f"commit_{step:08d}.json"
        commit.parent.mkdir(parents=True, exist_ok=True)
        commit.write_text("{}\n", encoding="utf-8")
        exchange = store.runtime / "exchange" / "slice_0000" / "force_artifacts"
        exchange.mkdir(parents=True, exist_ok=True)
        (exchange / f"force_step{step:08d}.json").write_text("{}\n", encoding="utf-8")

    def test_keeps_source_and_latest_three_steps_with_restart_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self._store(root)
            for sid in range(3):
                source = store.runtime / "cases" / f"slice_{sid:04d}" / "0"
                source.mkdir(parents=True, exist_ok=True)
                (source / "U").write_text("source\n", encoding="utf-8")
            for step in range(1, 7):
                self._materialize_step(store, step)
                store.commit_step(
                    step=step, time_s=step * 0.00125, integer_tick=step * 1_250_000,
                    checkpoint=self._checkpoint(step), compact_row=self._row(step),
                )
            for sid in range(3):
                case_root = store.runtime / "cases" / f"slice_{sid:04d}"
                names = {item.name for item in case_root.iterdir()}
                self.assertEqual(names, {"0", "0.005", "0.00625", "0.0075"})
            self.assertTrue((store.runtime / "checkpoint/checkpoint_00000006.json").is_file())
            self.assertFalse((store.runtime / "checkpoint/checkpoint_00000003.json").exists())
            latest = json.loads(store.index.read_text(encoding="utf-8"))
            previous = json.loads(store.previous_index.read_text(encoding="utf-8"))
            self.assertEqual((latest["global_step"], previous["global_step"]), (6, 5))
            self.assertEqual(store.recoverable_restart()["global_step"], 6)
            self.assertEqual(len(store.journal.read_text(encoding="utf-8").splitlines()), 6)

    def test_corrupt_latest_pointer_falls_back_to_previous_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            for step in range(1, 3):
                self._materialize_step(store, step)
                store.commit_step(
                    step=step, time_s=step * 0.00125, integer_tick=step * 1_250_000,
                    checkpoint=self._checkpoint(step), compact_row=self._row(step),
                )
            latest = json.loads(store.index.read_text(encoding="utf-8"))
            latest["checkpoint_sha256"] = "0" * 64
            store.index.write_text(json.dumps(latest), encoding="utf-8")
            recovered = store.recoverable_restart()
            self.assertEqual((recovered["global_step"], recovered["recovered"]), (1, True))

    def test_old_postprocessing_time_is_evicted_with_case_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), keep=2)
            for step in range(1, 5):
                self._materialize_step(store, step)
                post = store.runtime / "cases/slice_0000/postProcessing/forces" / format(step * 0.00125, ".12g")
                post.mkdir(parents=True, exist_ok=True)
                (post / "forces.dat").write_text("row\n", encoding="utf-8")
                store.commit_step(
                    step=step, time_s=step * 0.00125, integer_tick=step * 1_250_000,
                    checkpoint=self._checkpoint(step), compact_row=self._row(step),
                )
            self.assertFalse((store.runtime / "cases/slice_0000/postProcessing/forces/0.00125").exists())
            self.assertTrue((store.runtime / "cases/slice_0000/postProcessing/forces/0.00375").exists())

    def test_journal_failure_prevents_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            for step in range(1, 4):
                self._materialize_step(store, step)
                store.commit_step(
                    step=step, time_s=step * 0.00125, integer_tick=step * 1_250_000,
                    checkpoint=self._checkpoint(step), compact_row=self._row(step),
                )
            self._materialize_step(store, 4)
            with mock.patch.object(store, "append_journal", side_effect=RetentionError("journal unavailable")):
                with self.assertRaises(RetentionError):
                    store.commit_step(
                        step=4, time_s=0.005, integer_tick=5_000_000,
                        checkpoint=self._checkpoint(4), compact_row=self._row(4),
                    )
            self.assertTrue((store.runtime / "cases/slice_0000/0.00125").exists())
            self.assertTrue((store.runtime / "cases/slice_0000/0.0025").exists())

    def test_low_disk_fails_closed_before_new_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), min_free=100)
            with mock.patch.object(store, "_free_bytes", return_value=99):
                with self.assertRaises(RetentionError):
                    store.commit_step(
                        step=1, time_s=0.00125, integer_tick=1_250_000,
                        checkpoint=self._checkpoint(1), compact_row=self._row(1),
                    )
            self.assertFalse((store.runtime / "checkpoint/checkpoint_00000001.json").exists())

    def test_identity_and_checkpoint_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            with self.assertRaises(RetentionError):
                store.append_journal({**self._row(1), "integer_tick": 1_250_001})
            with self.assertRaises(RetentionError):
                store.commit_step(
                    step=1, time_s=0.00125, integer_tick=1_250_000,
                    checkpoint={**self._checkpoint(1), "case_id": "other"}, compact_row=self._row(1),
                )

    def test_ambiguous_time_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary), keep=1)
            self._materialize_step(store, 1)
            store.commit_step(
                step=1, time_s=0.00125, integer_tick=1_250_000,
                checkpoint=self._checkpoint(1), compact_row=self._row(1),
            )
            bad = store.runtime / "cases/slice_0000/0.0025001"
            bad.mkdir(parents=True)
            self._materialize_step(store, 3)
            with self.assertRaises(RetentionError):
                store.commit_step(
                    step=3, time_s=0.00375, integer_tick=3_750_000,
                    checkpoint=self._checkpoint(3), compact_row=self._row(3),
                )


if __name__ == "__main__":
    unittest.main()
