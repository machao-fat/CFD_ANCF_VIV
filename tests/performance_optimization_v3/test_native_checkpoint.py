from __future__ import annotations

import tempfile
import unittest
from coupling.checkpoint.atomic_checkpoint import _file_entry, CheckpointError
from unittest.mock import patch
from pathlib import Path

from coupling.performance_optimization_v2.openfoam_persistent import (
    PersistentOpenFOAMError,
    PersistentOpenFOAMSliceProcess,
)


class NativeCheckpointTests(unittest.TestCase):
    def _process(self, root: Path) -> PersistentOpenFOAMSliceProcess:
        case = root / "native" / "slice_0000"
        case.mkdir(parents=True)
        (case / "0").mkdir()
        (case / "2.20875").mkdir()
        (case / "0" / "motionScale").write_text("1\n", encoding="utf-8")
        (case / "2.20875" / "U").write_text("U\n", encoding="utf-8")
        process = PersistentOpenFOAMSliceProcess.__new__(PersistentOpenFOAMSliceProcess)
        process.case = case
        process.case_root = case.parent
        process._audit_case = root / "audit" / "slice_0000"
        process._native_wsl_case = "/tmp/cfd_ancf_viv_stage96/test/slice_0000"
        process._native_stage_created = True
        process._native_archive_complete = False
        process._native_checkpoint_paths = []
        process.native_checkpoint_direct = True
        process.runtime_config = type("Config", (), {"timeout_s": 1.0})()
        process.native_staging_audit = {"checkpoint_syncs": []}
        process._checkpoint_root_callback = lambda root_path: setattr(process, "callback_root", Path(root_path))
        process.slice_id = 0
        process.log_paths = []
        return process

    def test_direct_checkpoint_uses_native_source_and_records_hashes(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            root = Path(temp)
            process = self._process(root)
            files = {"openfoam_time_name": "2.20875", "case_relative_path": "slice_0000",
                     "static_files": {"motionScale": process.case / "0" / "motionScale"},
                     "time_files": {"U": process.case / "2.20875" / "U"}}
            result = process._sync_native_checkpoint(files)
            self.assertEqual(result["time_files"]["U"], files["time_files"]["U"])
            self.assertEqual(process.callback_root, process.case_root)
            self.assertEqual(process.native_staging_audit["checkpoint_syncs"][0]["mode"], "native_direct")
            self.assertEqual(len(process._native_checkpoint_paths), 2)

    def test_direct_checkpoint_rejects_missing_native_file(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            root = Path(temp)
            process = self._process(root)
            missing = process.case / "2.20875" / "p"
            files = {"openfoam_time_name": "2.20875", "case_relative_path": "slice_0000",
                     "static_files": {"motionScale": process.case / "0" / "motionScale"},
                     "time_files": {"p": missing}}
            with self.assertRaises(PersistentOpenFOAMError):
                process._sync_native_checkpoint(files)

    def test_archive_nonzero_robocopy_fails_closed(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            root = Path(temp)
            process = self._process(root)
            process._audit_case.mkdir(parents=True)
            process._native_checkpoint_paths = []
            process._native_wsl_case = "/tmp/cfd_ancf_viv_stage96/test/slice_0000"
            fake = type("Completed", (), {"returncode": 8, "stdout": "", "stderr": "copy failed"})()
            with patch("subprocess.run", return_value=fake):
                with self.assertRaises(PersistentOpenFOAMError):
                    process._archive_native_case()

    def test_native_cleanup_nonzero_fails_closed(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            process = self._process(Path(temp))
            fake = type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "cleanup failed"})()
            process._run_wsl_script = lambda script, timeout_s: fake
            with self.assertRaises(PersistentOpenFOAMError):
                process._cleanup_native_case()

    def test_prepare_hash_cache_records_identity_without_changing_manifest_entry(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            path = Path(temp) / "field"
            path.write_bytes(b"stable-field\n")
            cache = {}
            entry = _file_entry("2.0/U", path, cache=cache)
            self.assertEqual(entry["sha256"], cache[str(path.resolve())]["sha256"])
            self.assertEqual(entry["bytes"], cache[str(path.resolve())]["bytes"])
            self.assertGreater(cache[str(path.resolve())]["mtime_ns"], 0)
            path.write_bytes(b"changed-field\n")
            with self.assertRaises(CheckpointError):
                cached = cache[str(path.resolve())]
                if cached["bytes"] != path.stat().st_size or cached["mtime_ns"] != path.stat().st_mtime_ns:
                    raise CheckpointError("cached file identity changed")

    def test_compact_force_snapshot_writes_only_unique_validated_row(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            root = Path(temp)
            source = root / "forces.dat"
            source.write_text("# header\n2.0 ((1 2 3) (4 5 6))\n2.001 ((7 8 9) (1 1 1))\n", encoding="utf-8")
            destination = root / "snapshot.tmp"
            process = self._process(root)
            process.compact_force_snapshot = True
            force = type("Force", (), {"time_s": 2.001})()
            process._write_force_snapshot(source, destination, force)
            self.assertEqual(destination.read_text(encoding="utf-8"), "2.001 ((7 8 9) (1 1 1))\n")
            self.assertLess(destination.stat().st_size, source.stat().st_size)

    def test_compact_force_snapshot_rejects_non_unique_row(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            root = Path(temp)
            source = root / "forces.dat"
            source.write_text("2.0 ((1 2 3) (4 5 6))\n2.0 ((7 8 9) (1 1 1))\n", encoding="utf-8")
            process = self._process(root)
            process.compact_force_snapshot = True
            with self.assertRaises(PersistentOpenFOAMError):
                process._write_force_snapshot(source, root / "snapshot.tmp", type("Force", (), {"time_s": 2.0})())

    def test_field_write_format_rewrite_is_bounded(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            root = Path(temp)
            process = self._process(root)
            process_case = process.case / "system"
            process_case.mkdir(parents=True)
            control = process_case / "controlDict"
            control.write_text("writeFormat ascii;\n", encoding="utf-8")
            process.field_write_format = "binary"
            process._rewrite_field_write_format()
            self.assertIn("writeFormat binary;", control.read_text(encoding="utf-8"))

    def test_field_write_precision_rewrite_is_bounded(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path(temp)
            process = self._process(root)
            process.field_write_precision = 10
            process_case = process.case / "system"
            process_case.mkdir(parents=True)
            control = process_case / "controlDict"
            control.write_text("writePrecision 16;\n", encoding="utf-8")
            process._rewrite_field_write_precision()
            self.assertIn("writePrecision 10;", control.read_text(encoding="utf-8"))
