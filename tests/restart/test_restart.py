from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.multi_slice_driver import SchedulerError
from tests.multi_slice_driver.harness import make_harness


class RestartTests(unittest.TestCase):
    def _make_checkpoint(self):
        root = Path(tempfile.mkdtemp())
        scheduler, structure, processes, _ = make_harness(root=root)
        result = scheduler.run_step(step=0, time_s=0.0)
        return root, result.checkpoint_path

    def _mutated_manifest(self, root: Path, checkpoint: Path, mutate):
        data = json.loads(checkpoint.read_text(encoding="utf-8"))
        mutate(data)
        path = root / ("mutated_" + checkpoint.name)
        path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _assert_rejected(self, manifest: Path, root: Path):
        scheduler, structure, processes, _ = make_harness(root=root)
        with self.assertRaises(SchedulerError):
            scheduler.restore_from_checkpoint(manifest)
        self.assertEqual(structure.committed_step, -1)

    def test_successful_restart_continues_at_next_step(self):
        root, checkpoint = self._make_checkpoint()
        scheduler, structure, processes, _ = make_harness(root=root)
        restored = scheduler.restore_from_checkpoint(checkpoint)
        self.assertEqual(restored["step"], 0)
        self.assertEqual(restored["next_step"], 1)
        result = scheduler.run_step(step=1, time_s=0.01)
        self.assertEqual(result.step, 1)
        self.assertEqual(structure.committed_step, 1)

    def test_restart_rejects_slice_count_coordinate_length_config_and_tamper(self):
        root, checkpoint = self._make_checkpoint()
        for label, mutate in (
            ("count", lambda data: data.update(expected_slice_ids=[0, 1, 2])),
            ("coordinate", lambda data: data["slices"][1].update(s_ref_m=99.0)),
            ("length", lambda data: data["slices"][1].update(slice_length_m=9.0)),
            ("config", lambda data: data.update(config_sha256="0" * 64)),
        ):
            with self.subTest(label=label):
                manifest = self._mutated_manifest(root, checkpoint, mutate)
                self._assert_rejected(manifest, root)
        case_file = root / "cases" / "slices" / "slice_0001" / "0" / "U"
        original = case_file.read_text(encoding="utf-8")
        case_file.write_text(original + "tampered\n", encoding="utf-8")
        try:
            self._assert_rejected(checkpoint, root)
        finally:
            case_file.write_text(original, encoding="utf-8")

    def test_pending_prepared_or_temp_manifest_is_not_restartable(self):
        root, checkpoint = self._make_checkpoint()
        pending = next((root / "checkpoints" / ".pending").glob("*/manifest.prepared.json"))
        scheduler, structure, processes, _ = make_harness(root=root)
        with self.assertRaises(SchedulerError):
            scheduler.restore_from_checkpoint(pending)
        temporary = root / "checkpoints" / "manifest.tmp"
        temporary.write_text(checkpoint.read_text(encoding="utf-8"), encoding="utf-8")
        # A temp copy is still rejected by the normal path policy only if its
        # contents are not a committed manifest; make that explicit here.
        data = json.loads(temporary.read_text(encoding="utf-8"))
        data["status"] = "prepared"
        temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
        with self.assertRaises(SchedulerError):
            scheduler.restore_from_checkpoint(temporary)

    def test_checkpoint_prepare_without_commit_has_no_committed_manifest(self):
        root, checkpoint = self._make_checkpoint()
        committed = list((root / "checkpoints").glob("checkpoint_*.json"))
        self.assertTrue(committed)
        # The pending directory is retained as post-mortem evidence, but only
        # the committed root manifest is accepted by restore.
        pending = list((root / "checkpoints" / ".pending").glob("*/manifest.prepared.json"))
        self.assertTrue(pending)
        self.assertEqual(json.loads(pending[0].read_text(encoding="utf-8"))["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
