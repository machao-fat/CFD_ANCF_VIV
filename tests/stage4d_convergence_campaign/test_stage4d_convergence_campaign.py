import json
import unittest
from pathlib import Path

from src.coupling.stage4d_convergence_campaign import campaign


PROJECT = Path(r"D:\研二文件\开题准备\CFD_ANCF_VIV")
RESULTS = PROJECT / "results" / "07_stage4d_c_convergence"


class Stage4DConvergenceCampaignTests(unittest.TestCase):
    def test_template_contains_required_solver_entries_and_hash(self):
        identity = campaign.template_identity()
        self.assertEqual(identity["template_id"], "stage4d-c-convergence-template-v1")
        self.assertTrue(identity["template_sha256"])
        fv = (campaign.TEMPLATE_ROOT / "case_template" / "system" / "fvSolution").read_text(encoding="utf-8")
        for token in ("pcorr", "pcorrFinal", "cellMotionUx"):
            self.assertIn(token, fv)
        fv_solution = (campaign.TEMPLATE_ROOT / "case_template" / "system" / "fvSolution").read_text(encoding="utf-8")
        self.assertIn("correctPhi                  yes", fv_solution)
        self.assertIn("correctMeshPhi              yes", fv_solution)

    def test_node_positions_and_virtual_work_for_all_meshes(self):
        for n_elem in (2, 4, 8):
            result = campaign._virtual_work(n_elem)
            self.assertEqual(result["node_positions_m"], [10.0 * j / n_elem for j in range(n_elem + 1)])
            self.assertEqual(result["ndof"], 6 * (n_elem + 1))
            self.assertLessEqual(result["relative_error"], 1.0e-12)
            self.assertTrue(result["passed"])

    def test_nrmse_floor_and_alignment(self):
        self.assertEqual(campaign._nrmse([[0.0], [0.0]], [[0.0], [0.0]], 1.0e-8), 0.0)
        self.assertAlmostEqual(campaign._nrmse([[1.0], [2.0]], [[1.1], [1.9]], 1.0e-8), 0.0632455532031194)
        comparison = json.loads((RESULTS / "time_step_convergence.json").read_text(encoding="utf-8"))
        self.assertEqual(comparison["alignment"]["coarse_count"], 100)
        self.assertEqual(comparison["alignment"]["fine_count"], 200)
        self.assertEqual(comparison["alignment"]["aligned_count"], 100)

    def test_time_gate_failure_is_explicit_and_blocks_downstream(self):
        comparison = json.loads((RESULTS / "time_step_convergence.json").read_text(encoding="utf-8"))
        self.assertFalse(comparison["all_passed"])
        self.assertGreater(comparison["structure"]["qdot_nrmse"], 0.05)
        self.assertGreater(comparison["structure"]["qddot_nrmse"], 0.05)
        structure = json.loads((RESULTS / "structure_mesh_convergence.json").read_text(encoding="utf-8"))
        self.assertEqual(structure["status"], "not_run_blocked_by_time_step_gate")
        selected = json.loads((RESULTS / "selected_configuration.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["status"], "none")
        duration = json.loads((RESULTS / "staged_duration_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(duration["status"], "not_run_blocked_by_time_step_gate")

    def test_template_smoke_and_identity_evidence(self):
        audit = json.loads((RESULTS / "template_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["status"], "passed")
        self.assertEqual(audit["openfoam_version"], "OpenFOAM-10")
        self.assertEqual(audit["real_two_step_smoke"]["steps_completed"], 2)
        self.assertEqual(audit["real_two_step_smoke"]["process_peak"], 2)
        self.assertEqual(audit["real_two_step_smoke"]["matlab_start_count"], 1)
        self.assertEqual(audit["real_two_step_smoke"]["motionScale"]["production_sha256_expected"], campaign.PRODUCTION_MOTIONSCALE_HASH)

    def test_period_and_five_slice_scope(self):
        period = json.loads((RESULTS / "period_coverage_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(period["insufficient_for_viv_statistics"])
        plan = json.loads((RESULTS / "five_slice_flow_bank_requirements.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["status"], "planning_only")
        self.assertFalse(plan["real_five_slice_run"])


if __name__ == "__main__":
    unittest.main()
