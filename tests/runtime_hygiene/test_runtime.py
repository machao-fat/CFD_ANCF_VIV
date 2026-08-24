from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.coupling.runtime_hygiene import RUNTIME_SUBDIRECTORIES, build_task_environment, create_runtime_run, probe_python_runtime


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RuntimeHygieneTests(unittest.TestCase):
    def test_runtime_run_has_required_subdirectories_on_d_drive(self):
        run = create_runtime_run(PROJECT_ROOT, "runtime_hygiene_test")
        self.assertEqual(run.drive.upper(), "D:")
        self.assertEqual({path.name for path in run.iterdir()}, set(RUNTIME_SUBDIRECTORIES))

    def test_environment_is_task_scoped_and_d_drive(self):
        run = create_runtime_run(PROJECT_ROOT, "runtime_hygiene_test")
        env = build_task_environment(run, {"TEMP": "C:\\should-not-win"})
        for key in ("TEMP", "TMP", "TMPDIR", "PYTHONPYCACHEPREFIX", "PIP_CACHE_DIR", "MPLCONFIGDIR", "MATLAB_PREFDIR"):
            self.assertEqual(Path(env[key]).drive.upper(), "D:")
            self.assertTrue(Path(env[key]).is_dir())

    def test_probe_does_not_mutate_global_temp(self):
        before = tempfile.gettempdir()
        probe = probe_python_runtime()
        self.assertEqual(tempfile.gettempdir(), before)
        self.assertIn("tempfile_gettempdir", probe)

    def test_runtime_rejects_c_drive_on_windows(self):
        if os.name == "nt":
            with self.assertRaises(ValueError):
                create_runtime_run(Path("C:/"), "runtime_hygiene_rejected")


if __name__ == "__main__":
    unittest.main()
