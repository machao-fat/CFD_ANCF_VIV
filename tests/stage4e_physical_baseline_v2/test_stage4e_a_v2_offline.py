from __future__ import annotations

import json
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "08_stage4e_physical_baseline_v2"
EXPECTED_CSV_SHA = "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df"


def read(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


class Stage4EAV2OfflineAuditTests(unittest.TestCase):
    def test_source_hash_and_classification(self):
        d = read("source_correction_v2.json")
        self.assertEqual(d["selected_csv"]["sha256"], EXPECTED_CSV_SHA)
        self.assertFalse(d["selected_csv"]["raw_csv_written_to_project"])
        self.assertEqual(d["source_classification"]["Fu2022_JFS_103722"], "primary experiment")
        self.assertEqual(d["source_classification"]["Fu2025_MarineStructures_103895"], "numerical validation paper")

    def test_no_raw_csv_under_project(self):
        # Runtime/MATLAB work trees are execution artifacts, not test inputs;
        # skip them so disappearing worker temp directories cannot break discovery.
        csvs = []
        for current, dirs, files in os.walk(ROOT, topdown=True):
            dirs[:] = [d for d in dirs if d not in {"runtime", "matlab_environment", "tmp", "tmpdir", "prefdir", "pycache", "__pycache__"}]
            if "DSF_S0T1_V048_1.csv" in files:
                csvs.append(Path(current) / "DSF_S0T1_V048_1.csv")
        self.assertEqual(csvs, [])

    def test_schema_time_and_channel_counts(self):
        d = read("csv_schema_audit.json")
        self.assertEqual(d["encoding"], "gb18030")
        self.assertEqual(d["data_rows"], 18000)
        self.assertEqual(d["data_columns"], 56)
        self.assertEqual(d["source_time_column"]["unique_count"], 73)
        self.assertEqual(d["derived_index_time"]["dt_s"], 0.004)
        self.assertTrue(d["all_data_finite"])
        self.assertEqual(len(d["channel_groups"]["CF1_4"]), 4)
        self.assertEqual(len(d["channel_groups"]["CF1_5"]), 5)
        self.assertEqual(len(d["channel_groups"]["IL1_6"]), 6)
        self.assertEqual(len(d["channel_groups"]["IL1_8"]), 8)

    def test_processing_boundary_and_observables(self):
        d = read("processed_observables_v048.json")
        self.assertEqual(d["status"], "completed_with_filter_boundary")
        self.assertEqual(d["preprocessing"]["filter_equivalence"], "not_proven: public repository lacks bpass.m or its documented order/phase")
        self.assertTrue(d["preprocessing"]["raw_values_preserved_in_processing"])
        self.assertTrue(d["not_a_raw_data_redistribution"])
        self.assertTrue(d["raw_observables"]["force_stats_N"]["Fy"]["finite_count"] == 18000)
        cf_cols = [tuple(x["source_columns"]) for x in d["raw_observables"]["cf_repair_metadata"]]
        il_cols = [x["source_column"] for x in d["raw_observables"]["il_repair_metadata"]]
        self.assertEqual(len(set(cf_cols)), 9)
        self.assertEqual(len(set(il_cols)), 14)

    def test_wet_measured_and_calculated_separate(self):
        d = read("wet_modal_validation.json")
        self.assertTrue(d["calculated_and_measured_are_separate"])
        self.assertEqual(d["experimental_wet_frequencies_Hz"], [1.59, 3.14, 4.78])
        self.assertEqual(d["paper_calculated_wet_f1_Hz"], 1.51)
        self.assertEqual(d["Cm"], 1.0)
        self.assertEqual(d["status"], "diagnostic_added_mass_only")

    def test_target_modes_and_mesh_rule(self):
        d = read("target_mode_mesh_convergence.json")
        self.assertEqual(d["target_modes"]["CF_order1"], [0, 2])
        self.assertEqual(d["target_modes"]["IL_order2"], [2, 4])
        self.assertEqual(d["target_modes"]["IL_order4"], [6, 8])
        self.assertFalse(d["decision"]["nElem4_vs_nElem8_target_mode_frequency_pass"])
        self.assertTrue(d["decision"]["nElem8_vs_nElem16_target_mode_frequency_pass"])
        self.assertEqual(d["decision"]["recommended_minimum_target_mode_nElem"], 8)
        for pair in ("comparison_4_vs_8", "comparison_8_vs_16"):
            for metric in d[pair].values():
                self.assertIn("principal_angle_max_deg", metric)
                self.assertIn("subspace_MAC_min", metric)

    def test_slice_design_and_signs(self):
        d = read("bidirectional_slice_design.json")
        self.assertEqual(d["recommended_minimum_quadrature_slices_for_absU_and_U2_5pct"], 5)
        self.assertLessEqual(d["slice_designs"]["5"]["relative_errors_vs_dense"]["int_U2_m3ps2_relative_error"], 0.05)
        self.assertLess(d["slice_designs"]["5"]["slices"][0]["Ulocal_mps"], 0.48)
        signs = {s["flow_sign"] for s in d["slice_designs"]["5"]["slices"]}
        self.assertIn("positive", signs)
        self.assertIn("negative", signs)

    def test_no_real_cfd_and_conditional_freeze(self):
        d = read("stage4e_a_v2_candidate_summary.json")
        self.assertFalse(d["real_cfd_started"])
        self.assertEqual(d["status"], "partially_completed")
        freeze = read("primary_benchmark_freeze_candidate_v2.json")
        self.assertEqual(freeze["status"], "conditionally_frozen_offline_only")
        self.assertFalse(freeze["real_cfd_started"])

    def test_cost_is_estimate_not_run(self):
        d = read("cost_and_architecture_estimate.json")
        self.assertEqual(d["status"], "planning_estimate_only")
        self.assertGreater(d["slice_count_estimates"]["5"]["estimated_wall_s_per_global_step"], 0)
        self.assertIn("no new CFD run", d["slice_count_estimates"]["5"]["estimate_boundary"])


if __name__ == "__main__":
    unittest.main()
