from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class Stage362OfflineAuditTests(unittest.TestCase):
    def test_audit_is_offline_and_detects_mesh_collapse(self) -> None:
        root = Path(__file__).resolve().parents[2]
        script = root / "tools/stage362_restart_mesh_quality_audit_v1/audit.py"
        completed = subprocess.run([sys.executable, str(script)], cwd=root, check=True, capture_output=True, text=True)
        self.assertIn('"gate": "pass"', completed.stdout)
        report = json.loads((root / "results/362_restart_mesh_quality_audit_v1/mesh_quality_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(report["offline_only"])
        self.assertEqual(report["real_process_counts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        finding = report["finding"]
        self.assertTrue(finding["point_displacement_and_mesh_points_consistent"])
        self.assertTrue(finding["local_mesh_compression_observed"])
        self.assertTrue(finding["cylinder_u_boundary_reset_to_uniform_zero"])
        self.assertEqual(finding["root_cause_class"], "restart_mesh_quality_collapse_after_motion_update")


if __name__ == "__main__":
    unittest.main()
