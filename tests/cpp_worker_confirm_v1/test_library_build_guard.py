from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.contracts import REAL_AUTHORIZATION_TOKEN, ContractError
from coupling.cpp_worker_confirm_v1.library_build_guard import (
    LibraryBuildError, prepare_fresh_library_build, require_build_authorization,
)


class LibraryBuildGuardTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "src" / "ancfFileMotion"
        (source / "lnInclude").mkdir(parents=True)
        (source / "ancfFileMotion.C").write_text("source\n", encoding="utf-8")
        (source / "ancfFileMotion.H").write_text("header\n", encoding="utf-8")
        (source / "lnInclude" / "ancfFileMotion.H").write_text("header\n", encoding="utf-8")
        return source

    def test_prepare_isolated_copy_never_launches_external_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = prepare_fresh_library_build(
                project_root=root, runtime=root / "runtime", results=root / "results",
                source_tree=self._source(root),
            )
            self.assertEqual(plan["source_file_count"], 3)
            self.assertFalse(plan["launch_performed"])
            self.assertEqual(plan["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
            self.assertTrue((root / "results" / "fresh_library_build_plan.json").is_file())

    def test_rejects_nonempty_runtime_and_legacy_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self._source(root)
            runtime = root / "runtime"; runtime.mkdir(); (runtime / "partial").write_text("x")
            with self.assertRaises(LibraryBuildError):
                prepare_fresh_library_build(project_root=root, runtime=runtime, results=root / "results", source_tree=source)

    def test_external_build_requires_exact_authorization(self):
        require_build_authorization(execute=False, authorization=None)
        with self.assertRaises(ContractError):
            require_build_authorization(execute=True, authorization=None)
        require_build_authorization(execute=True, authorization=REAL_AUTHORIZATION_TOKEN)

    def test_old_legacy_path_is_not_a_fresh_build_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "stage4f_three_slice_bridge_precision_repair_v1" / "src"
            source.mkdir(parents=True)
            with self.assertRaises(LibraryBuildError):
                prepare_fresh_library_build(project_root=root, runtime=root / "runtime", results=root / "results", source_tree=source)


if __name__ == "__main__":
    unittest.main()
