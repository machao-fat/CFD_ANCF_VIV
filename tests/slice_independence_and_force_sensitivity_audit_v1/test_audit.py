from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.slice_independence_audit_v1.audit import (exact_file_equality, force_object_status, motion_path_status, parse_forces,
    sensitivity_evidence_status, synthetic_channel_probe)


def force_row(fy: float) -> str:
    return f"0 ((0 {fy} 0) (0 0 0)) ((0 0 0) (0 0 0))\n"


class SliceIndependenceAuditTests(unittest.TestCase):
    def test_future_launcher_keeps_the_openfoam10_point_motion_path_complete(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / "tools" / "three_slice_force_contract_smoke_v1" / "run_smoke.py").read_text(encoding="utf-8")
        self.assertIn("namePointDisplacement pointDisplacement", source)
        self.assertIn("lower { type symmetryPlane; }", source)
        self.assertIn("upper { type symmetryPlane; }", source)
        self.assertIn("cellDisplacementFinal", source)

    def test_three_force_file_parser_is_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"slice_{index}" / "forces.dat" for index in range(3)]
            for index, path in enumerate(paths, start=1):
                path.parent.mkdir(); path.write_text(force_row(float(index)), encoding="utf-8")
            self.assertEqual([parse_forces(path)[0.0]["total_N"][1] for path in paths], [1.0, 2.0, 3.0])
            self.assertFalse(exact_file_equality(paths))
            self.assertEqual(len({str(path.resolve()) for path in paths}), 3)

    def test_declared_channels_do_not_broadcast(self):
        pairs = [{"displacement_from": f"Structure_{i:04d}", "displacement_to": f"Fluid_{i:04d}",
                  "force_from": f"Fluid_{i:04d}", "force_to": f"Structure_{i:04d}"} for i in range(3)]
        self.assertEqual(synthetic_channel_probe(pairs)["status"], "pass")
        pairs[2]["displacement_from"] = "Structure_0000"
        self.assertEqual(synthetic_channel_probe(pairs)["status"], "fail")

    def test_displacement_laplacian_requires_point_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dynamic = root / "dynamicMeshDict"; dynamic.write_text("solver displacementLaplacian;", encoding="utf-8")
            broken = motion_path_status({"point_displacement_field": "unused"}, dynamic, root / "20" / "pointDisplacement", root / "20" / "polyMesh" / "points")
            fixed = motion_path_status({"point_displacement_field": "pointDisplacement"}, dynamic, root / "20" / "pointDisplacement", root / "20" / "polyMesh" / "points")
            self.assertEqual(broken["status"], "fail")
            self.assertEqual(fixed["status"], "pass")

    def test_force_function_must_integrate_cylinder_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controlDict"
            path.write_text('functions { cylinderForces { type forces; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }', encoding="utf-8")
            self.assertEqual(force_object_status(path)["status"], "pass")
            path.write_text('functions { cylinderForces { type forces; patches (inlet); } }', encoding="utf-8")
            self.assertEqual(force_object_status(path)["status"], "fail")

    def test_controlled_motion_sensitivity_requires_all_observables(self):
        self.assertEqual(sensitivity_evidence_status(geometry_distinct=True, u_distinct=True, p_distinct=True, fy_difference_N=1e-6), "pass")
        self.assertEqual(sensitivity_evidence_status(geometry_distinct=True, u_distinct=True, p_distinct=True, fy_difference_N=0.0), "fail")


if __name__ == "__main__":
    unittest.main()
