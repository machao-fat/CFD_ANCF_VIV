from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

import numpy as np

from src.coupling.stage4e_target_re_pilot_v2_2.analysis_v2_2 import (
    compare_statistics,
    gci_pair,
    merge_force_history,
    overlap_force_audit,
    parse_cfl,
    statistics_gate,
)
from src.coupling.stage4e_target_re_pilot_v2_2.case_generator_v2_2 import MESH_LEVELS, mesh_family_definition
from src.coupling.stage4e_target_re_pilot_v2_2.identity_v2_2 import AREF, B_MESH, D, HARD_CFL, finite


class V22Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(os.environ.get("B2A_V2_2_TEST_RUNTIME", Path.cwd() / "runtime" / "stage4e_b2_a_v2_2" / "unit_tests"))
        root.mkdir(parents=True, exist_ok=True)
        cls.root = root / "contract-fixtures"
        if cls.root.exists():
            shutil.rmtree(cls.root)
        cls.root.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.root.exists():
            shutil.rmtree(cls.root)

    def _force_file(self, name: str, offset: float = 0.0, mismatch: float = 0.0) -> Path:
        path = self.root / name
        rows = [
            f"# time pressure_x pressure_y pressure_z viscous_x viscous_y viscous_z\n",
            f"{0.0+offset:.12g} 1 2 3 0.1 0.2 0.3\n",
            f"{0.4+offset:.12g} 1.1 2.1 3.1 0.11 0.21 {0.31+mismatch:.12g}\n",
        ]
        path.write_text("".join(rows), encoding="utf-8")
        return path

    def test_b_mesh_is_d_and_aref(self) -> None:
        self.assertAlmostEqual(B_MESH, D, places=15)
        self.assertAlmostEqual(AREF, D * B_MESH, places=15)

    def test_force_history_overlap_equivalence(self) -> None:
        a = self._force_file("a.dat")
        b = self._force_file("b.dat")
        result = overlap_force_audit([a, b])
        self.assertTrue(result["passed"])
        self.assertEqual(result["records"][0]["overlap_sample_count"], 2)

    def test_inconsistent_overlap_is_rejected(self) -> None:
        a = self._force_file("c.dat")
        b = self._force_file("d.dat", mismatch=1.0)
        self.assertFalse(overlap_force_audit([a, b])["passed"])
        with self.assertRaises(ValueError):
            merge_force_history([a, b])

    def test_duplicate_force_time_can_be_deduplicated(self) -> None:
        a = self._force_file("e.dat")
        b = self._force_file("f.dat")
        merged = merge_force_history([a, b])
        self.assertTrue(merged["available"])
        self.assertEqual(merged["removed_duplicate_rows"], 2)

    def test_cfl_hard_stop_boundary_is_not_relaxed(self) -> None:
        path = self.root / "cfl.log"
        path.write_text("Courant Number mean: 0.1 max: 0.8\n", encoding="utf-8")
        self.assertEqual(parse_cfl(path)["max_cfl"], HARD_CFL)
        self.assertFalse(parse_cfl(path)["passed"])

    def test_mesh_family_refinement_ratio(self) -> None:
        family = mesh_family_definition()
        self.assertTrue(all(item["topology_same"] for item in family["levels"]))
        self.assertEqual([MESH_LEVELS[name]["radial_layers"] for name in ("coarse", "medium", "fine")], [12, 16, 24])
        self.assertGreater(MESH_LEVELS["fine"]["cells_per_sector"], MESH_LEVELS["medium"]["cells_per_sector"])
        self.assertAlmostEqual(MESH_LEVELS["medium"]["target_first_center_m"] / MESH_LEVELS["fine"]["target_first_center_m"], 2.0)

    def test_statistics_gate_rejects_non_evaluable_frequency(self) -> None:
        time = np.linspace(0.0, 20.0, 201)
        raw = np.column_stack([time, np.ones((len(time), 6))])
        path = self.root / "constant_force.dat"
        np.savetxt(path, raw)
        from src.coupling.stage4e_target_re_pilot_v2_2.analysis_v2_2 import merge_force_history
        result = merge_force_history([path])
        gate = statistics_gate(result, U_abs=0.43414375179615955, runtime_valid=True, force_crosscheck_passed=True, production_max_cfl=0.4)
        self.assertFalse(gate["statistics_valid"])

    def test_compare_statistics_threshold(self) -> None:
        self.assertTrue(compare_statistics({"mean_Cd": 1.0}, {"mean_Cd": 1.01}, limits={"mean_Cd": 0.02})["passed"])
        self.assertFalse(compare_statistics({"mean_Cd": 1.0}, {"mean_Cd": 1.03}, limits={"mean_Cd": 0.02})["passed"])

    def test_gci_only_for_finite_distinct_values(self) -> None:
        self.assertTrue(gci_pair(1.1, 1.05, 2.0)["available"])
        self.assertFalse(gci_pair(1.0, 1.0, 2.0)["available"])

    def test_no_slice_length_in_case_contract(self) -> None:
        self.assertNotIn("slice_length_m", json.dumps({"b_mesh_m": B_MESH, "Aref_OF_m2": AREF}))

    def test_json_finite_rejects_nan(self) -> None:
        with self.assertRaises(ValueError):
            finite(float("nan"))
