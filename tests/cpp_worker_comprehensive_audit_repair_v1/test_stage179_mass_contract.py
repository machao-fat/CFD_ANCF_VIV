from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = Path(os.environ.get(
    "CFD_ANCF_STAGE_BUILD",
    str(ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "stage179_mass_contract_build"),
))
SELFTEST = BUILD_ROOT / "Release" / "cfd_ancf_physics_ownership_selftest.exe"


class MassQuadratureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SELFTEST.is_file():
            raise unittest.SkipTest("Stage179 physics ownership selftest has not been built")

    def test_mass_quadrature_is_fixed_five_point_like_matlab(self) -> None:
        completed = subprocess.run(
            [str(SELFTEST)], cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        record = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(record["status"], "pass")
        self.assertTrue(record["mass_order_contract"])
        self.assertLessEqual(record["mass_order_difference"],
                             1.0e-14 * record["mass_order_scale"] if "mass_order_scale" in record else 1.0e-8)


if __name__ == "__main__":
    unittest.main()
