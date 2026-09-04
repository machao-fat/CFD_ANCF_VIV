import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ConsistentPotentialLauncherTests(unittest.TestCase):
    def test_launcher_is_bound_and_requires_explicit_authorization(self):
        path = ROOT / "tools/cpp_worker_fresh_t0_v1/run_authorized_consistent_potential_001.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("run_20260827_meshfix11", text)
        self.assertIn("consistent_real_run_001", text)
        result = subprocess.run([sys.executable, str(path)], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--authorize-real", result.stderr)


if __name__ == "__main__":
    unittest.main()
