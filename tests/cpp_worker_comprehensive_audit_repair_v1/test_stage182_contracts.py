from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = Path(os.environ.get(
    "CFD_ANCF_STAGE_BUILD",
    str(ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "stage182_build"),
))
OWNERSHIP_SELFTEST = BUILD_ROOT / "Release" / "cfd_ancf_physics_ownership_selftest.exe"


class Stage182ContractTests(unittest.TestCase):
    def test_force_representation_and_state_lineage_guards_are_present(self) -> None:
        ownership = (ROOT / "src" / "coupling" / "cpp_physics_ownership_v1" /
                     "physics_ownership.cpp").read_text(encoding="utf-8")
        self.assertIn("unsupported force representation", ownership)
        for relative in (
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
            "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("state.step != static_cast<std::size_t>(global_step)", text)
            self.assertIn("std::abs(state.time_s - time_s) > 1.0e-12", text)

    @unittest.skipUnless(OWNERSHIP_SELFTEST.is_file(), "Stage182 Release selftest has not been built")
    def test_unknown_force_representation_is_rejected_by_selftest(self) -> None:
        completed = subprocess.run(
            [str(OWNERSHIP_SELFTEST)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["unknown_representation_rejected"])


if __name__ == "__main__":
    unittest.main()
