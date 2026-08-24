import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
from scipy.io import loadmat


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3_2"


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


class ModalExportTests(unittest.TestCase):
    def test_matlab_modal_exports_are_real_and_finite(self):
        audit = read("ancf_modal_state_export_audit.json")
        self.assertEqual(audit["matlab_start_count"], 1)
        self.assertFalse(audit["openfoam_started"])
        for n, expected_ndof in ((8, 54), (16, 102)):
            d = loadmat(OUT / f"ancf_modal_state_nElem{n}.mat")
            self.assertEqual(d["qmode"].shape, (expected_ndof, 12))
            self.assertTrue(np.isfinite(d["qmode"]).all())
            item = audit["per_nElem"][str(n)]
            self.assertEqual(item["qmode_shape"], [expected_ndof, 12])
            self.assertLess(item["max_abs_fixed_qmode"], 1e-14)
            self.assertLess(item["max_mass_orthogonality_error"], 1e-12)
            self.assertLess(item["max_eigen_residual_relative"], 1e-9)

    def test_fixed_dofs_are_zero_and_mass_normalized(self):
        for n in (8, 16):
            d = loadmat(OUT / f"ancf_modal_state_nElem{n}.mat")
            q = d["qmode"]
            fixed = d["fixed_dof_1based"].ravel().astype(int) - 1
            free = d["free_dof_1based"].ravel().astype(int) - 1
            M = d["mass_matrix"]
            V = d["V_free_mass_normalized"]
            self.assertLess(np.max(np.abs(q[fixed, :])), 1e-14)
            Mff = M[np.ix_(free, free)]
            self.assertTrue(np.allclose(V.T @ Mff @ V, np.eye(V.shape[1]), atol=1e-12, rtol=0.0))


class CrosscheckAndHTests(unittest.TestCase):
    def test_old_new_frequencies_and_subspaces(self):
        cross = read("old_new_modal_crosscheck.json")
        for n in ("8", "16"):
            self.assertLessEqual(cross["per_nElem"][n]["max_frequency_relative_error_first8"], 1e-10)
            for item in cross["per_nElem"][n]["target_subspace_crosscheck"].values():
                self.assertGreaterEqual(item["subspace_MAC_min"], .999)

    def test_formal_mapping_and_physical_projection(self):
        h = read("formal_H_projection_with_qmode.json")
        self.assertEqual(h["status"], "completed_formal_H_with_real_qmode")
        self.assertEqual(h["basis_tests"]["slope_columns_nonzero"], True)
        self.assertLess(h["basis_tests"]["rigid_translation_max_error"], 1e-12)
        self.assertLess(h["basis_tests"]["linear_axis_z_max_error_m"], 1e-12)
        for grid in h["per_grid"].values():
            for label in ("CF_mode_1", "IL_mode_2", "IL_mode_4"):
                self.assertGreaterEqual(grid[label]["subspace"]["subspace_MAC_min"], .95)
                self.assertLessEqual(grid[label]["max_slice_relative_error_physical_scaled"], .01)

    def test_physical_and_mass_normalized_amplitudes_are_separate(self):
        h = read("formal_H_projection_with_qmode.json")
        for grid in h["per_grid"].values():
            for label in ("CF_mode_1", "IL_mode_2", "IL_mode_4"):
                self.assertIn("rms_target_m", grid[label])
                self.assertIn("physical_scaled_slice_displacements_8", grid[label])


class SliceRobustnessTests(unittest.TestCase):
    def test_seven_nine_candidates_and_single_length_weight(self):
        data = read("seven_nine_slice_candidates.json")
        self.assertEqual(len(data["candidates"]), 6)
        for item in data["candidates"].values():
            self.assertTrue(item["delta_s_applied_once"])
            self.assertGreater(len(item["slice_lengths_m"]), 0)
            self.assertTrue(all(x > 0 for x in item["slice_lengths_m"]))
            self.assertEqual(len(item["modal_weighted_loads"]), 3)
            self.assertEqual(set(item["modal_weighted_loads"]), {"1", "2", "4"})

    def test_fixed_seed_uncertainty_and_direction_stability(self):
        data = read("seven_nine_uncertainty.json")
        self.assertEqual(data["seed"], 20260812)
        self.assertEqual(data["sample_count"], 1000)
        self.assertTrue(data["fixed_candidate_boundaries"])
        for method in ("linear", "pchip"):
            for item in data["per_method"][method].values():
                self.assertEqual(item["direction_changes"], 0)
        self.assertTrue(data["per_method"]["linear"]["zero_crossing_aware_7_point_sampling"]["robust_pass"])
        self.assertTrue(data["per_method"]["pchip"]["zero_crossing_aware_7_point_sampling"]["robust_pass"])

    def test_il2_amplitude_not_used_as_strict_evidence(self):
        # This v3.2 package preserves the v3.1 amplitude classification.
        v3 = json.loads((ROOT / "results" / "08_stage4e_physical_baseline_v3_1" / "amplitude_robustness_classification.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(v3["explicit_IL2_bandpass_relative_RMS_span"], 0.11648535, delta=1e-6)
        self.assertEqual(v3["explicit_IL2_bandpass_not_strict_amplitude"], True)


class BidirectionalProtocolTests(unittest.TestCase):
    def test_route_g_signed_global_and_restart_identity(self):
        g = read("bidirectional_route_G_candidate.json")
        self.assertEqual(g["schema_version"], "0.2.1")
        self.assertFalse(g["mock"]["force_rotation"])
        self.assertTrue(g["restart_signed_U_change_rejected"])
        self.assertEqual(g["R_GL"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])

    def test_route_l_rotation_virtual_work_and_inactive(self):
        route = read("bidirectional_route_L_0_2_2_candidate.json")
        self.assertEqual(route["candidate_schema_version"], "0.2.2-candidate")
        self.assertLessEqual(route["virtual_work_max_abs_residual"], 1e-12)
        self.assertTrue(route["inactive_no_cfd_ready_wait"])
        self.assertTrue(route["inactive_force_exact_zero"])
        self.assertTrue(route["restart_R_active_flow_sign_change_rejected"])
        self.assertTrue(route["formal_0_2_1_unchanged"])


class ProvenanceTests(unittest.TestCase):
    def test_no_openfoam_and_source_pin(self):
        summary = read("stage4e_a_v3_2_final_candidate_summary.json")
        pin = read("source_pin_and_hash.json")
        self.assertFalse(summary["openfoam_started"])
        self.assertEqual(pin["commit_sha"], "fe251f958ddf2f083b53cdb53a9d2addde85e17e")
        self.assertEqual(pin["csv_sha256_observed"], "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df")
        self.assertEqual(pin["main1_sha256_observed"], "a2ab54340f2269afad1249d8c99b26b1e5aab2cd1691786c2c428dda64d0c963")
        self.assertFalse(pin["raw_csv_written_to_project"])


if __name__ == "__main__":
    unittest.main()
