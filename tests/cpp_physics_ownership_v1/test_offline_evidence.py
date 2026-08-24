from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "152_cpp_physics_ownership_v1"


class OfflineEvidenceTests(unittest.TestCase):
    def test_physics_selftest_passed(self) -> None:
        data = json.loads((RESULTS / "physics_selftest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "pass")
        for field in (
            "load_balance", "force_representation", "tangent_finite_difference",
            "tangent_symmetric", "rigid_translation", "rigid_rotation", "virtual_work",
            "restart_equivalent", "zero_load_limit", "axial_patch", "component_limits",
            "newmark_consistent", "time_step_convergence", "grid_convergence",
            "invalid_representation_rejected", "invalid_line_weight_rejected",
            "mass_symmetric", "mass_positive_samples",
        ):
            self.assertTrue(data[field], field)

    def test_worker_replay_passed_without_external_processes(self) -> None:
        data = json.loads((RESULTS / "offline_40step_worker_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "pass")
        self.assertEqual(data["steps_completed"], 40)
        self.assertEqual(data["worker_start_count"], 1)
        self.assertTrue(data["response_identity_continuous"])
        self.assertLessEqual(data["base_load_external_max_abs_error"], 1.0e-8)
        self.assertEqual(data["physical_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        self.assertEqual(data["owned_residual"], 0)

    def test_ten_step_replay_passed(self) -> None:
        data = json.loads((RESULTS / "offline_10step_worker_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "pass")
        self.assertEqual(data["steps_completed"], 10)
        self.assertEqual(data["worker_start_count"], 1)
        self.assertEqual(data["physical_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        self.assertEqual(data["owned_residual"], 0)

    def test_faults_fail_closed(self) -> None:
        data = json.loads((RESULTS / "failure_injection_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "pass")
        self.assertTrue(all(data["cases"].values()))
        self.assertFalse(data["same_runtime_retry"])
        self.assertEqual(data["owned_residual"], 0)

    def test_numeric_diagnostics_passed(self) -> None:
        data = json.loads((RESULTS / "convergence_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "pass")
        self.assertTrue(data["time_step"]["finite"])
        self.assertTrue(data["long_double_vs_double_solve"]["finite"])
        self.assertEqual(data["owned_residual"], 0)

    def test_contract_and_mass_audits_passed(self) -> None:
        contract = json.loads((RESULTS / "contract_mismatch_audit.json").read_text(encoding="utf-8"))
        mass = json.loads((RESULTS / "matlab_cpp_mass_matrix_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["status"], "pass")
        self.assertEqual(contract["mismatch_fields"], {})
        self.assertEqual(mass["status"], "pass")
        self.assertTrue(mass["hash_match"])
        self.assertFalse(mass["matlab_process_started"])


if __name__ == "__main__":
    unittest.main()
