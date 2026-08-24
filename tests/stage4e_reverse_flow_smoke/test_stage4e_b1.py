import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4e_reverse_flow_smoke.smoke import (
    D_M,
    EFLUX_LIMIT,
    MAX_CFL,
    MESH_TOL,
    PARENT_FLOW,
    RESULT_ROOT,
    build_template,
    canonical_sha,
    check_case_freshness,
    field_audit,
    force_audit,
    mesh_audit,
    validate_solver_result,
)


RUN_ID = "stage4e_b1_20260812T155537Z_586210c4"
RUN = RESULT_ROOT / RUN_ID


class RouteGBoundarySmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.positive = RUN / "positive"
        cls.negative = RUN / "negative"
        cls.config = json.loads((RUN / "route_g_smoke_config.json").read_text(encoding="utf-8"))
        cls.summary = json.loads((RUN / "stage4e_b1_gate_candidate_summary.json").read_text(encoding="utf-8"))

    def test_positive_left_inlet_right_outlet(self):
        self.assertEqual(self.config["positive_boundary_roles"], {"left": "velocity_inlet", "right": "pressure_outlet"})

    def test_negative_right_inlet_left_outlet(self):
        self.assertEqual(self.config["negative_boundary_roles"], {"right": "velocity_inlet", "left": "pressure_outlet"})

    def test_signed_global_velocities(self):
        self.assertEqual(self.config["positive_U_global_mps"], [1.0, 0.0, 0.0])
        self.assertEqual(self.config["negative_U_global_mps"], [-1.0, 0.0, 0.0])

    def test_internal_initial_fields_are_mirrored(self):
        p = (self.positive / "0/U").read_text(encoding="utf-8")
        n = (self.negative / "0/U").read_text(encoding="utf-8")
        self.assertIn("internalField uniform (1 0 0)", p)
        self.assertIn("internalField uniform (-1 0 0)", n)

    def test_cylinder_center_is_identical(self):
        self.assertEqual(self.config["cylinder_center_m"], [0.0, 0.0, 0.0])

    def test_mesh_hash_and_mirror_topology(self):
        audit = json.loads((RUN / "mesh_symmetry_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["passed"])
        self.assertTrue(audit["same_polyMesh_hashes"])
        self.assertLessEqual(audit["max_point_coordinate_error_m"], MESH_TOL)
        self.assertLessEqual(audit["max_cell_center_coordinate_error_m"], MESH_TOL)

    def test_force_configuration_has_no_extra_rotation(self):
        control = "\n".join(line for line in (self.positive / "system/controlDict").read_text(encoding="utf-8").splitlines() if not line.strip().startswith("//"))
        self.assertNotIn("coordinateRotation", control)
        self.assertNotIn("axesRotation", control)
        self.assertTrue(json.loads((RUN / "boundary_role_audit.json").read_text(encoding="utf-8"))["global_force_coordinates"])

    def test_positive_negative_solver_settings_are_equal(self):
        for relative in ("system/controlDict", "system/fvSchemes", "system/fvSolution", "constant/physicalProperties", "constant/momentumTransport"):
            self.assertEqual((self.positive / relative).read_bytes(), (self.negative / relative).read_bytes())

    def test_smoke_hash_recomputes(self):
        config = dict(self.config)
        expected = config.pop("smoke_config_sha256")
        self.assertEqual(canonical_sha(config), expected)

    def test_parent_flow_profile_is_unchanged(self):
        source = json.loads(PARENT_FLOW.read_text(encoding="utf-8"))
        self.assertEqual(source["flow_profile_sha256"], self.summary["parent_flow_profile_sha256"])
        source_audit = json.loads((RUN / "source_hash_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(source_audit["parent_evidence_unchanged"])

    def test_old_case_contamination_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "case"
            (case / "0").mkdir(parents=True)
            (case / "0.025").mkdir()
            with self.assertRaises(RuntimeError):
                check_case_freshness(case)

    def test_solver_failure_stops(self):
        with self.assertRaises(RuntimeError):
            validate_solver_result({"return_code": 1, "contains_end": False, "contains_fatal": True, "contains_nan_inf": False})

    def test_cfl_limit_stops(self):
        with self.assertRaises(RuntimeError):
            validate_solver_result({"return_code": 0, "contains_end": True, "contains_fatal": False, "contains_nan_inf": False}, max_cfl=MAX_CFL)

    def test_nan_inf_stops(self):
        with self.assertRaises(RuntimeError):
            validate_solver_result({"return_code": 0, "contains_end": True, "contains_fatal": False, "contains_nan_inf": True})

    def test_force_global_sign_comparison(self):
        audit = json.loads((RUN / "force_symmetry_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["passed"])
        self.assertLess(audit["E_Fx"], 0.02)
        self.assertLess(audit["E_Cd"], 0.02)

    def test_velocity_field_mirror_comparison(self):
        audit = json.loads((RUN / "field_symmetry_audit.json").read_text(encoding="utf-8"))
        self.assertLessEqual(audit["max_E_U"], 0.02)

    def test_demeaned_pressure_mirror_comparison(self):
        audit = json.loads((RUN / "field_symmetry_audit.json").read_text(encoding="utf-8"))
        self.assertLessEqual(audit["max_E_p"], 0.02)

    def test_boundary_flux_conservation(self):
        audit = json.loads((RUN / "flux_conservation_audit.json").read_text(encoding="utf-8"))
        self.assertLessEqual(audit["positive"]["E_flux"], EFLUX_LIMIT)
        self.assertLessEqual(audit["negative"]["E_flux"], EFLUX_LIMIT)

    def test_frequency_gate_is_rejected_for_short_window(self):
        self.assertEqual(self.summary["frequency_gate"], "frequency_not_evaluable_for_gate")

    def test_process_limiter_has_no_leak(self):
        audit = json.loads((RUN / "process_concurrency_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["max_processes"], 2)
        self.assertFalse(audit["permit_leak"])
        self.assertTrue(audit["enforced"])

    def test_both_cases_completed_formal_steps(self):
        for name in ("positive_case_summary.json", "negative_case_summary.json"):
            summary = json.loads((RUN / name).read_text(encoding="utf-8"))
            self.assertEqual(summary["formal_return_code"], 0)
            self.assertEqual(summary["formal_steps_completed"], 200)
            self.assertTrue(summary["logs_contain_end"])
            self.assertFalse(summary["fatal_or_nan_inf"])

    def test_case_freshness_passed(self):
        audit = json.loads((RUN / "case_freshness_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(all(item["fresh"] for item in audit["cases"].values()))

    def test_template_is_independent_and_finite(self):
        audit = build_template()
        self.assertFalse(audit["generated_output"])
        self.assertEqual(len(audit["template_sha256"]), 64)

    def test_final_gate_candidate_status(self):
        self.assertEqual(self.summary["status"], "passed_with_scope_limits")
        self.assertTrue(self.summary["smoke_measurements_passed"])
        self.assertEqual(self.summary["route_G_boundary_gate_recommendation"], "建议不通过")
        self.assertTrue(self.summary["no_high_re_or_viv_claim"])


if __name__ == "__main__":
    unittest.main()
