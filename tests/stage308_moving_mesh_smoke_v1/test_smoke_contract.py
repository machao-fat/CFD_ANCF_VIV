from __future__ import annotations

import unittest

from coupling.stage307_moving_mesh_repair_v1.repair import audit_case_configuration, corrected_precice_dict, corrected_point_displacement


class Stage308ContractTests(unittest.TestCase):
    def test_all_three_participants_are_distinct_and_bound(self) -> None:
        for index in range(3):
            result = audit_case_configuration(
                precice_dict=corrected_precice_dict(index),
                point_displacement=corrected_point_displacement(),
                velocity="boundaryField { cyl { type movingWallVelocity; value uniform (0 0 0); } }",
                dynamic_mesh="dynamicFvMesh dynamicMotionSolverFvMesh; solver displacementLaplacian;",
                expected_participant=f"Fluid_{index:04d}",
            )
            self.assertEqual(result["status"], "pass")

    def test_scope_is_eight_steps(self) -> None:
        source = open("tools/stage308_moving_mesh_smoke_v1/run_stage308_smoke.py", encoding="utf-8").read()
        self.assertIn("STEPS = 8", source)
        self.assertIn("TARGET_TIME = STEPS * DT", source)
        self.assertIn("namePointDisplacement pointDisplacement", source)
        self.assertIn("mover", source)
        self.assertIn('"displacementLaplacian"', source)
        self.assertIn("runtime_point_displacement", source)
        self.assertIn("allow_calculated_point=False", source)
        self.assertIn("calculated point patch is not castable", source)
        self.assertIn("cell_displacement_cyl_nonzero", source)
        self.assertIn("moved_mesh_points_sha256", source)
        self.assertIn("launcher_preflight.log", source)
        self.assertIn("openfoam_env_init.log", source)
        self.assertIn("import precice, coupling", source)
        self.assertIn("--stage-id", source)
        self.assertIn("args.run_id", source)
        self.assertIn("if gate_status == \"pass\" else 1", source)
        self.assertIn("--profile", source)
        self.assertIn("profile in (\"optimized\", \"optimized_mesh_once\")", source)
        self.assertIn("optimized_mesh_once", source)

    def test_audited_optimized_profile_keeps_per_step_output(self) -> None:
        source = open("tools/stage308_moving_mesh_smoke_v1/run_stage308_smoke.py", encoding="utf-8").read()
        self.assertIn('profile == "optimized_audited"', source)
        self.assertIn("optimize_control_dict(control, write_interval=1, binary=True)", source)
        self.assertIn('"optimized_audited")', source)

    def test_native_mesh_method_profiles_are_explicit(self) -> None:
        source = open("tools/stage308_moving_mesh_smoke_v1/run_stage308_smoke.py", encoding="utf-8").read()
        for method in ("uniform", "inverseDistance", "quadratic", "exponential", "sbrStress"):
            self.assertIn(f'"{method}"', source)
        self.assertIn("expected_motion_solver=", source)

    def test_native_dynamic_mesh_dictionaries_are_distinct(self) -> None:
        from coupling.stage307_moving_mesh_repair_v1.repair import audit_case_configuration
        from importlib.util import module_from_spec, spec_from_file_location
        from pathlib import Path

        path = Path("tools/stage308_moving_mesh_smoke_v1/run_stage308_smoke.py")
        spec = spec_from_file_location("stage308_smoke", path)
        module = module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        for method in ("uniform", "inverseDistance", "quadratic", "exponential", "sbrStress"):
            mesh = module.corrected_dynamic_mesh(method)
            solver = "displacementSBRStress" if method == "sbrStress" else "displacementLaplacian"
            self.assertIn(f"motionSolver    {solver};", mesh)
            self.assertEqual(audit_case_configuration(
                precice_dict=corrected_precice_dict(0),
                point_displacement=corrected_point_displacement(),
                velocity="boundaryField { cyl { type movingWallVelocity; value uniform (0 0 0); } }",
                dynamic_mesh=mesh,
                expected_participant="Fluid_0000",
                expected_motion_solver=solver,
            )["status"], "pass")


if __name__ == "__main__":
    unittest.main()
