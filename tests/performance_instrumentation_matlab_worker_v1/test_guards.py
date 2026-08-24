from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.performance_instrumentation_matlab_worker_v1.guards import (
    OwnedProcessRegistry, no_real_process_start, reject_old_artifact,
    restart_state_after_windows_restart, validate_runtime_scope,
)
from coupling.performance_instrumentation_matlab_worker_v1.protocol import ProtocolError


class GuardTests(unittest.TestCase):
    def test_owned_child_grandchild_cleanup_preserves_non_owned(self):
        registry = OwnedProcessRegistry()
        registry.register(100, owned=True)
        registry.register(101, parent_pid=100, owned=True)
        registry.register(102, parent_pid=101, owned=True)
        registry.register(900, parent_pid=100, owned=False)
        result = registry.cleanup_owned_tree(100)
        self.assertEqual(result["residual"], 0)
        self.assertFalse(result["non_owned_closed"])
        self.assertNotIn(900, result["closed_owned_pids"])

    def test_scope_and_forbidden_process_guards(self):
        root = Path("D:/runtime/performance_instrumentation_matlab_worker_v1/run")
        self.assertEqual(validate_runtime_scope(root), root.resolve())
        with self.assertRaises(ProtocolError):
            validate_runtime_scope(Path("C:/runtime/performance_instrumentation_matlab_worker_v1/run"))
        with self.assertRaises(ProtocolError):
            no_real_process_start({"MATLAB": 1, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
        no_real_process_start({"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})

    def test_old_artifact_and_restart_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            allowed = Path(temp) / "performance_instrumentation_matlab_worker_v1" / "run"
            foreign = Path(temp) / "old_stage66" / "partial.json"
            with self.assertRaises(ProtocolError):
                reject_old_artifact(artifact_path=foreign, allowed_runtime=allowed)
        self.assertEqual(restart_state_after_windows_restart(), "IDLE_WAITING_FOR_CONTRACT")


if __name__ == "__main__":
    unittest.main()
