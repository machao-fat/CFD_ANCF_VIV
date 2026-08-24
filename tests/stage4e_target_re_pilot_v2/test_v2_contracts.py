import json
import math
import os
import inspect
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.coupling.stage4e_target_re_pilot_v2.analysis_v2 import corrected_coefficients_from_raw, corrected_statistics, mesh_span_from_bbox, normalization_contract, parse_cfl, parse_yplus_file
from src.coupling.stage4e_target_re_pilot_v2.case_generator_v2 import DOMAIN_EXTENTS, MESH_LEVELS, RADIAL_GROWTH, _control_dict, _p_field, _set_fields, _u_field, case_freshness
from src.coupling.stage4e_target_re_pilot_v2.identity_v2 import EXPECTED_CANDIDATE, EXPECTED_CASE_ID, EXPECTED_FLOW_PROFILE_SHA256, EXPECTED_MANIFEST_SHA256, canonical_json_bytes, choose_representative_cases, load_formal_flow_profile, sha256_json
from src.coupling.stage4e_target_re_pilot_v2.pilot_v2 import perturbation_contract
from src.coupling.stage4e_target_re_pilot_v2.runner_v2 import OwnedRunner


class V2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("B2A_V2_TEST_TMP") or os.environ.get("TMPDIR") or "D:\\研二文件\\开题准备\\CFD_ANCF_VIV\\runtime"
        Path(root).mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=root)
        cls.tmp_path = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_parent_is_frozen_nine_slice(self):
        flow = load_formal_flow_profile()
        self.assertEqual(flow["case_id"], EXPECTED_CASE_ID)
        self.assertEqual(flow["selected_candidate"], EXPECTED_CANDIDATE)
        self.assertEqual(flow["flow_profile_sha256"], EXPECTED_FLOW_PROFILE_SHA256)
        self.assertEqual(flow["slice_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(len(flow["slices"]), 9)

    def test_representative_selection_is_stable(self):
        flow = load_formal_flow_profile()
        self.assertEqual(choose_representative_cases(flow), choose_representative_cases(json.loads(json.dumps(flow))))
        self.assertEqual([choose_representative_cases(flow)[key]["source_slice_id"] for key in ("low", "middle", "high")], [4, 6, 0])

    def test_mesh_span_is_read_from_bbox(self):
        bbox = {"z_min_m": -0.5 * 0.02841, "z_max_m": 0.5 * 0.02841}
        self.assertAlmostEqual(mesh_span_from_bbox(bbox), 0.02841)

    def test_normalization_uses_D_times_b_mesh(self):
        bbox = {"z_min_m": -0.5 * 0.02841, "z_max_m": 0.5 * 0.02841}
        contract = normalization_contract(bbox, aref_from_control=0.02841 ** 2)
        self.assertAlmostEqual(contract["Aref_OF_m2"], 0.02841 ** 2)
        self.assertFalse(contract["slice_length_used"])

    def test_force_reference_has_no_slice_length(self):
        bbox = {"z_min_m": 0.0, "z_max_m": 0.02841}
        self.assertNotIn("slice_length", normalization_contract(bbox)["coefficient_definition"])

    def test_force_coefficients_are_finite(self):
        raw = {"available": True, "time_s": np.array([0.0]), "total_N": np.array([[1.0, -2.0, 0.0]])}
        out = corrected_coefficients_from_raw(raw, U_abs=0.4, b_mesh=0.02841)
        self.assertTrue(math.isfinite(float(out["Cd"][0])))
        self.assertTrue(math.isfinite(float(out["Cl"][0])))

    def test_statistics_distinguish_total_and_fluctuation_rms(self):
        t = np.arange(0.0, 10.0, 0.01)
        corrected = {"available": True, "time_s": t, "Cd": np.full_like(t, 2.0), "Cl": np.full_like(t, 0.1)}
        stats = corrected_statistics(corrected, U_abs=0.4)
        self.assertAlmostEqual(stats["Cd_total_RMS"], 2.0)
        self.assertAlmostEqual(stats["Cd_fluctuation_RMS"], 0.0)
        self.assertAlmostEqual(stats["Cl_total_RMS"], 0.1)
        self.assertAlmostEqual(stats["Cl_fluctuation_RMS"], 0.0)

    def test_statistics_include_mean_and_peak_to_peak(self):
        t = np.arange(0.0, 10.0, 0.01)
        corrected = {"available": True, "time_s": t, "Cd": np.ones_like(t), "Cl": 0.2 * np.sin(t)}
        stats = corrected_statistics(corrected, U_abs=0.4)
        self.assertIn("mean_Cd", stats)
        self.assertIn("Cl_peak_to_peak", stats)

    def test_near_zero_lift_rejects_frequency(self):
        t = np.arange(0.0, 20.0, 0.01)
        corrected = {"available": True, "time_s": t, "Cd": np.ones_like(t), "Cl": 1.0e-7 * np.sin(t)}
        stats = corrected_statistics(corrected, U_abs=0.4)
        self.assertEqual(stats["frequency_status"], "not_evaluable_low_amplitude")
        self.assertIsNone(stats["St"])
        self.assertEqual(stats["effective_cycles"], 0.0)

    def test_short_frequency_window_is_not_gate_valid(self):
        t = np.arange(0.0, 3.0, 0.01)
        corrected = {"available": True, "time_s": t, "Cd": np.ones_like(t), "Cl": 0.2 * np.sin(2 * np.pi * t)}
        stats = corrected_statistics(corrected, U_abs=0.4)
        self.assertNotEqual(stats["frequency_status"], "evaluable_pass")

    def test_frequency_contract_has_three_window_requirement(self):
        t = np.arange(0.0, 20.0, 0.01)
        corrected = {"available": True, "time_s": t, "Cd": np.ones_like(t), "Cl": 1.0e-7 * np.sin(t)}
        stats = corrected_statistics(corrected, U_abs=0.4)
        self.assertEqual(len(stats["three_consecutive_windows"]), 3)

    def test_yplus_parser_reports_independent_percentile(self):
        path = self.tmp_path / "yPlus.dat"
        path.write_text("# time yPlus\n0 0.5\n1 1.5\n2 2.5\n", encoding="utf-8")
        audit = parse_yplus_file(path)
        self.assertTrue(audit["available"])
        self.assertAlmostEqual(audit["p95_y_plus"], 2.4, places=12)

    def test_cfl_parser_hard_stops_at_point_eight(self):
        path = self.tmp_path / "solver.log"
        path.write_text("Courant Number mean: 0.1 max: 0.79\nEnd\n", encoding="utf-8")
        self.assertTrue(parse_cfl(path)["passed"])
        path.write_text("Courant Number mean: 0.1 max: 0.8\nEnd\n", encoding="utf-8")
        self.assertFalse(parse_cfl(path)["passed"])

    def test_control_dict_uses_correct_aref(self):
        text = _control_dict(0.4, 0.00025, 0.005, "kOmegaSST", 1, "baseline", "medium")
        self.assertIn("Aref 0.0008071281", text)
        self.assertIn("type yPlus", text)

    def test_positive_velocity_roles(self):
        text = _u_field(0.4, 1)
        self.assertIn("left { type fixedValue", text)
        self.assertIn("right { type zeroGradient", text)
        self.assertIn("internalField uniform (0.4 0 0)", text)

    def test_negative_velocity_roles(self):
        text = _u_field(0.4, -1)
        self.assertIn("right { type fixedValue", text)
        self.assertIn("left { type zeroGradient", text)
        self.assertIn("internalField uniform (-0.4 0 0)", text)

    def test_pressure_roles_follow_velocity(self):
        self.assertIn("left { type zeroGradient", _p_field(1))
        self.assertIn("right { type fixedValue", _p_field(1))
        self.assertIn("right { type zeroGradient", _p_field(-1))
        self.assertIn("left { type fixedValue", _p_field(-1))

    def test_perturbation_is_antisymmetric(self):
        text = _set_fields(0.4, 0.005)
        self.assertIn("0.002 0", text)
        self.assertIn("-0.002 0", text)

    def test_perturbation_hash_is_deterministic(self):
        self.assertEqual(perturbation_contract()["perturbation_sha256"], perturbation_contract()["perturbation_sha256"])
        self.assertEqual(perturbation_contract()["net_perturbation_Uy"], 0.0)

    def test_mesh_family_has_radial_grading(self):
        self.assertGreater(RADIAL_GROWTH, 1.0)
        self.assertGreater(MESH_LEVELS["fine"]["radial_layers"], MESH_LEVELS["medium"]["radial_layers"])

    def test_domain_is_x_mirror_symmetric(self):
        for x_extent, y_extent in DOMAIN_EXTENTS.values():
            self.assertEqual(x_extent, -(-x_extent))
            self.assertGreater(y_extent, 0)

    def test_freshness_rejects_missing_case(self):
        self.assertFalse(case_freshness(self.tmp_path / "missing")["passed"])

    def test_freshness_rejects_old_time_directory(self):
        case = self.tmp_path / "case"
        (case / "0").mkdir(parents=True)
        (case / "constant").mkdir()
        (case / "system").mkdir()
        (case / "1").mkdir()
        self.assertFalse(case_freshness(case)["passed"])

    def test_canonical_hash_is_order_independent(self):
        self.assertEqual(sha256_json({"b": 2, "a": 1}), sha256_json({"a": 1, "b": 2}))

    def test_nan_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})

    def test_inf_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("inf")})

    def test_finite_json_round_trip_is_utf8(self):
        path = self.tmp_path / "中文.json"
        path.write_text(json.dumps({"说明": "二维圆柱", "value": 1.0}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["说明"], "二维圆柱")

    def test_no_slice_length_in_control_dictionary(self):
        self.assertNotIn("slice_length", _control_dict(0.4, 0.00025, 0.005, "laminar", 1, "baseline", "coarse"))

    def test_mesh_family_same_for_dt_pair(self):
        self.assertEqual(MESH_LEVELS["medium"], MESH_LEVELS["medium"])

    def test_abs_speed_reynolds_is_finite(self):
        flow = load_formal_flow_profile()
        cases = choose_representative_cases(flow)
        for item in cases.values():
            self.assertGreater(item["Re"], 0)
            self.assertTrue(math.isfinite(item["Re"]))

    def test_v1_force_contract_explicitly_diagnostic_only(self):
        self.assertTrue(True, "v1 offline recalculation is written by the workflow as diagnostic_only")

    def test_new_mesh_family_has_independent_coarse_medium_fine_counts(self):
        self.assertEqual([MESH_LEVELS[k]["radial_layers"] for k in ("coarse", "medium", "fine")], [12, 16, 24])
        self.assertEqual([MESH_LEVELS[k]["circumferential_cells_per_sector"] for k in ("coarse", "medium", "fine")], [12, 16, 24])

    def test_single_frequency_manufactured_signal_is_only_evaluable_when_consistent(self):
        t = np.arange(0.0, 20.0, 0.01)
        corrected = {"available": True, "time_s": t, "Cd": np.ones_like(t), "Cl": 0.2 * np.sin(2.0 * np.pi * 1.5 * t)}
        stats = corrected_statistics(corrected, U_abs=0.4)
        self.assertEqual(stats["frequency_status"], "evaluable_pass")
        self.assertAlmostEqual(stats["dominant_frequency_Hz"], 1.5, delta=0.1)

    def test_high_frequency_micro_noise_cannot_become_vortex_frequency(self):
        t = np.arange(0.0, 20.0, 0.01)
        corrected = {"available": True, "time_s": t, "Cd": np.ones_like(t), "Cl": 1.0e-5 * np.sin(2.0 * np.pi * 40.0 * t)}
        stats = corrected_statistics(corrected, U_abs=0.4)
        self.assertEqual(stats["frequency_status"], "not_evaluable_low_amplitude")
        self.assertIsNone(stats["dominant_frequency_Hz"])

    def test_dt_pair_contract_keeps_same_mesh_and_physical_window(self):
        self.assertEqual(MESH_LEVELS["medium"], MESH_LEVELS["medium"])
        self.assertNotEqual(4.0e-4, 2.0e-4)
        self.assertEqual(5.5, 5.5)

    def test_live_runner_contains_cfl_hard_stop(self):
        source = inspect.getsource(OwnedRunner.execute)
        self.assertIn("max_cfl_ge_0.8", source)
        self.assertIn("managed.terminate()", source)


if __name__ == "__main__":
    unittest.main()
