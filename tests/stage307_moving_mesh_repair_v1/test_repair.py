from __future__ import annotations

import unittest

from coupling.stage307_moving_mesh_repair_v1.repair import (
    RepairError,
    audit_case_configuration,
    audit_motion_observations,
    corrected_precice_dict,
    corrected_point_displacement,
)


POINT = corrected_point_displacement()
VELOCITY = """boundaryField { cyl { type movingWallVelocity; value uniform (0 0 0); } }"""
DYNAMIC = """dynamicFvMesh dynamicMotionSolverFvMesh; solver displacementLaplacian;"""


class ConfigurationTests(unittest.TestCase):
    def test_corrected_configuration_binds_point_field(self) -> None:
        for index in range(3):
            result = audit_case_configuration(
                precice_dict=corrected_precice_dict(index),
                point_displacement=POINT,
                velocity=VELOCITY,
                dynamic_mesh=DYNAMIC,
                expected_participant=f"Fluid_{index:04d}",
            )
            self.assertEqual(result["status"], "pass")

    def test_unused_binding_fails_closed(self) -> None:
        broken = corrected_precice_dict(0).replace("namePointDisplacement pointDisplacement;", "namePointDisplacement unused;")
        result = audit_case_configuration(
            precice_dict=broken,
            point_displacement=POINT,
            velocity=VELOCITY,
            dynamic_mesh=DYNAMIC,
            expected_participant="Fluid_0000",
        )
        self.assertEqual(result["status"], "do_not_pass")

    def test_wrong_boundary_type_fails_closed(self) -> None:
        broken = POINT.replace("cyl { type fixedValue;", "cyl { type calculated;")
        result = audit_case_configuration(
            precice_dict=corrected_precice_dict(0),
            point_displacement=broken,
            velocity=VELOCITY,
            dynamic_mesh=DYNAMIC,
            expected_participant="Fluid_0000",
        )
        self.assertEqual(result["status"], "do_not_pass")


class MotionTests(unittest.TestCase):
    @staticmethod
    def row(step: int, *, same_force: bool = False) -> dict[str, object]:
        forces = {sid: ("a" if same_force else sid[-1]) * 64 for sid in ("slice_0000", "slice_0001", "slice_0002")}
        return {
            "global_step": step,
            "slice_motion": {"slice_0000": (0.01 * step, 0.0), "slice_0001": (0.02 * step, 0.0), "slice_0002": (0.03 * step, 0.0)},
            "slice_force_hashes": forces,
        }

    def test_distinct_motion_and_force_pass(self) -> None:
        result = audit_motion_observations([self.row(1), self.row(2)])
        self.assertEqual(result["status"], "pass")

    def test_force_broadcast_fails_closed(self) -> None:
        result = audit_motion_observations([self.row(1, same_force=True)])
        self.assertEqual(result["status"], "do_not_pass")

    def test_nonfinite_motion_fails_closed(self) -> None:
        row = self.row(1)
        row["slice_motion"]["slice_0001"] = (float("nan"), 0.0)  # type: ignore[index]
        with self.assertRaises(RepairError):
            audit_motion_observations([row])

    def test_empty_motion_fails_closed(self) -> None:
        with self.assertRaises(RepairError):
            audit_motion_observations([])


if __name__ == "__main__":
    unittest.main()
