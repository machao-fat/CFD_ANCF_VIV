from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LibraryBuildExecutionTests(unittest.TestCase):
    def test_default_is_dry_run_and_never_starts_wsl(self):
        project = Path(__file__).resolve().parents[2]
        script = project / "tools/cpp_worker_confirm_v1/run_fresh_library_build.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root / "runtime"; results = root / "results"
            runtime.mkdir(); (runtime / "source" / "ancfFileMotion").mkdir(parents=True)
            completed = subprocess.run([sys.executable, str(script), "--runtime", str(runtime), "--results", str(results)],
                                       cwd=project, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0)
            audit = json.loads((results / "fresh_library_build_execution_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "prepared_only")
            self.assertEqual(audit["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})

    def test_execute_without_authorization_fails_before_wsl(self):
        project = Path(__file__).resolve().parents[2]
        script = project / "tools/cpp_worker_confirm_v1/run_fresh_library_build.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root / "runtime"; results = root / "results"
            runtime.mkdir(); (runtime / "source" / "ancfFileMotion").mkdir(parents=True)
            completed = subprocess.run([sys.executable, str(script), "--execute", "--runtime", str(runtime), "--results", str(results)],
                                       cwd=project, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            audit = json.loads((results / "fresh_library_build_execution_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["failure_classification"], "missing_explicit_authorization")
            self.assertEqual(audit["real_process_starts"]["WSL"], 0)


if __name__ == "__main__":
    unittest.main()
