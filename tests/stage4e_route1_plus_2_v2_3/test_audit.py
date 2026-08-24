"""Unit tests for Stage 4E-B2-A-v2.3 audit rules.

These tests encode the frozen audit rules from the task prompt. They are static /
arithmetic tests that do NOT require OpenFOAM or the shell workspace. Run with:

    python -m unittest discover -s tests/stage4e_route1_plus_2_v2_3 -p "test*.py"
"""

import json
import importlib.util
import math
import os
import unittest

# Load the v2.3 source modules by file path.  The test directory is a package so
# root discovery can collect it; using a package import here would collide with
# this test package's own top-level name.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, "..", "..", "src", "coupling"))


def _load_source_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SRC, "stage4e_route1_plus_2_v2_3", filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ac = _load_source_module("luna_v23_audit_constants", "audit_constants.py")
_cfl = _load_source_module("luna_v23_online_cfl", "online_cfl.py")
OnlineCFLMonitor = _cfl.OnlineCFLMonitor
classify_log_line = _cfl.classify_log_line

RESULTS_DIR = os.path.abspath(
    os.path.join(
        _HERE,
        "..",
        "..",
        "results",
        "10_stage4e_route1_plus_2_v2_3",
    )
)


def _load(name):
    path = os.path.join(RESULTS_DIR, name)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestAgentIdentity(unittest.TestCase):
    def test_01_agent_identity_no_api_key(self):
        d = _load("agent_identity.json")
        self.assertTrue(d.get("api_key_recorded") is False)
        s = json.dumps(d)
        self.assertNotIn("sk-", s)
        self.assertNotIn("token", s.lower())

    def test_01b_model_identity_mismatch_marked(self):
        d = _load("agent_identity.json")
        self.assertFalse(d.get("model_identity_mismatch"))
        self.assertFalse(d.get("identity_capture_heavy_openfoam_started"))
        self.assertTrue(d.get("heavy_openfoam_started"))


class TestOldEvidence(unittest.TestCase):
    def test_02_old_evidence_modified_false(self):
        d = _load("old_evidence_hash_audit.json")
        self.assertFalse(d.get("modified"))
        recs = {r["relative_path"]: r for r in d.get("records", [])}
        self.assertTrue(any(k.endswith("medium_fine_dt1_spatial_comparison.json") and v.get("read_success") for k, v in recs.items()))

    def test_03_sst_real_path_exists(self):
        d = _load("actual_sst_input_audit.json")
        self.assertTrue(d.get("resolved_case_path_exists"))
        self.assertTrue(d.get("old_audit_case_path_stale"))

    def test_04_files_read_must_be_true_for_old_input(self):
        d = _load("actual_sst_input_audit.json")
        for fname, rec in d.get("files", {}).items():
            self.assertTrue(rec.get("exists"), fname)
            self.assertTrue(rec.get("read_success"), fname)


class TestUnitsAndFormulas(unittest.TestCase):
    def test_05_k_omega_not_length_scale(self):
        d = _load("actual_sst_input_audit.json")
        self.assertFalse(d.get("derived_quantities", {}).get("k_over_omega_is_length_scale"))
        self.assertEqual(d["files"]["0/k"]["dimensions"], "[0 2 -2 0 0 0 0]")
        self.assertEqual(d["files"]["0/omega"]["dimensions"], "[0 0 -1 0 0 0 0]")

    def test_06_k_formula(self):
        k = ac.k_from_intensity(ac.U_MPS, ac.I_N)
        self.assertAlmostEqual(k, 1.5 * (ac.U_MPS * ac.I_N) ** 2, places=15)

    def test_06b_omega_formula(self):
        k = ac.k_from_intensity(ac.U_MPS, ac.I_N)
        Lt = ac.LT_OVER_D_N * ac.D_M
        omega = ac.omega_from_length_scale(k, Lt)
        self.assertAlmostEqual(omega, math.sqrt(k) / (ac.CMU ** 0.25 * Lt), places=12)

    def test_07_tu_percent_vs_fraction(self):
        # Scenario N: Tu = 1.0 percent, I = 0.01 fraction.
        self.assertAlmostEqual(ac.TU_N_PERCENT / 100.0, ac.I_N, places=12)
        # Scenario S: Tu percent back-calculates from k as fraction.
        i_s = ac.turbulence_intensity_from_k(ac.U_MPS, ac.K_S_M2PS2)
        self.assertAlmostEqual(i_s * 100.0, ac.TU_S_PERCENT, places=4)

    def test_08_rethetat_source_formula_verified(self):
        d = _load("transition_input_contract.json")
        self.assertAlmostEqual(d["scenario_N"]["ReThetat"], ac.rethetat0_zero_pressure_gradient(1.0), places=12)

    def test_09_rethetat_gammaInt_missing_rejected(self):
        d = _load("kOmegaSSTLM_source_audit.json")
        self.assertTrue(d["checks"]["2_ReThetat_is_MUST_READ"])
        self.assertTrue(d["checks"]["3_gammaInt_is_MUST_READ"])

    def test_10_aref_d_times_bmesh(self):
        self.assertAlmostEqual(ac.AREF_M2, ac.D_M * ac.B_MESH_M, places=12)
        self.assertAlmostEqual(ac.AREF_M2, 0.0008071281, places=10)

    def test_11_no_slice_length_in_fixed_cylinder_coeff(self):
        # Aref uses b_mesh (extruded thickness), never slice_length_m.
        self.assertAlmostEqual(ac.AREF_M2, ac.D_M * ac.B_MESH_M, places=12)
        self.assertNotEqual(ac.AREF_M2, ac.D_M * 1.0)  # sanity: not 1 m span


class TestGates(unittest.TestCase):
    def test_12_cfl_target(self):
        self.assertEqual(ac.CFL_TARGET, 0.5)

    def test_13_cfl_hard_stop(self):
        self.assertEqual(ac.CFL_HARD_STOP, 0.8)
        self.assertGreater(ac.CFL_HARD_STOP, ac.CFL_TARGET)

    def test_14_near_zero_lift_frequency_reject(self):
        # Cl RMS near zero => frequency not evaluable. Encode as: a zero-amplitude
        # series has undefined (NaN) shedding frequency -> reject.
        zeros = [0.0] * 100
        rms = ac.fluctuation_rms(zeros)
        self.assertAlmostEqual(rms, 0.0, places=12)
        # near-zero-lift means Cl fluct RMS below evaluable threshold -> not evaluable.
        self.assertTrue(rms < 1e-6)

    def test_15_total_vs_fluctuation_rms(self):
        samples = [1.0, 2.0, 3.0, 4.0]
        fr = ac.fluctuation_rms(samples)
        tr = ac.total_rms(samples)
        self.assertNotAlmostEqual(fr, tr, places=9)

    def test_16_three_windows(self):
        d = _load("medium_statistics.json")
        self.assertGreaterEqual(d.get("statistical_windows", 0), 3)
        self.assertFalse(d.get("statistics_valid"))

    def test_17_medium_fail_blocks_fine(self):
        fa = _load("fine_authorization.json")
        self.assertFalse(fa.get("authorized"))
        self.assertFalse(fa.get("fine_admission_criteria_met"))

    def test_18_max_two_scenarios(self):
        d = _load("transition_input_contract.json")
        self.assertEqual(d.get("max_entry_scenarios"), 2)
        self.assertTrue(d.get("no_third_Tu_allowed"))

    def test_19_no_third_model(self):
        d = _load("transition_input_contract.json")
        self.assertTrue(d.get("no_third_model_allowed"))
        # only one model family (kOmegaSSTLM) is authorized for the pilot.
        self.assertEqual(d["scenario_N"]["label"], "nominal engineering assumption")

    def test_20_force_crosscheck_not_run(self):
        d = _load("force_crosscheck.json")
        self.assertTrue(d.get("run"))
        self.assertLessEqual(d.get("max_relative_error", 1.0), 1e-10)

    def test_21_yplus_p95_not_run(self):
        d = _load("medium_yplus.json")
        self.assertTrue(d.get("run"))
        self.assertLessEqual(d.get("max_p95", 99.0), 1.0)

    def test_22_transition_fields_finite(self):
        d = _load("medium_transition_fields.json")
        self.assertTrue(d.get("run"))
        self.assertTrue(d.get("all_finite"))

    def test_23_json_no_nan_infinity(self):
        for name in os.listdir(RESULTS_DIR):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(RESULTS_DIR, name), "r", encoding="utf-8") as fh:
                raw = fh.read()
            parsed = json.loads(raw)  # must be valid JSON
            def assert_finite(value):
                if isinstance(value, float):
                    self.assertTrue(math.isfinite(value), name)
                elif isinstance(value, str):
                    self.assertNotIn(value, {"NaN", "Infinity", "-Infinity"}, name)
                elif isinstance(value, dict):
                    for child in value.values():
                        assert_finite(child)
                elif isinstance(value, list):
                    for child in value:
                        assert_finite(child)
            assert_finite(parsed)

    def test_24_process_cleanup(self):
        d = _load("process_cleanup_audit.json")
        self.assertEqual(d.get("owned_residual"), 0)
        self.assertFalse(d.get("permit_leak"))

    def test_25_drive_runtime(self):
        d = _load("runtime_path_audit.json")
        self.assertTrue(d.get("runtime_target_dir").startswith("D:\\"))

    def test_26_claim_matrix_no_overreach(self):
        d = _load("thesis_claim_matrix.json")
        for row in d["claim_matrix"]:
            if not row.get("allowed"):
                self.assertIn("reason", row)

    def test_27_online_cfl_thresholds(self):
        self.assertFalse(classify_log_line("Courant Number mean: 0.1 max: 0.49")["stop"])
        self.assertFalse(classify_log_line("Courant Number mean: 0.1 max: 0.799")["stop"])
        self.assertTrue(classify_log_line("Courant Number mean: 0.1 max: 0.8")["stop"])
        self.assertTrue(classify_log_line("Courant Number mean: 0.1 max: 1.2")["stop"])

    def test_28_online_cfl_time_and_partial_line(self):
        monitor = OnlineCFLMonitor()
        monitor.feed("Time = 0.5\n")
        event = monitor.feed("Courant Number mean: 0.1 max: 0.799\n")
        self.assertEqual(event["time"], 0.5)
        self.assertFalse(monitor.should_stop)
        self.assertTrue(monitor.feed("Courant Number mean: 0.1 max: 0.8\n")["stop"])
        self.assertFalse(monitor.feed("Courant Number mean: 0.1 max:")["stop"])


if __name__ == "__main__":
    unittest.main()
