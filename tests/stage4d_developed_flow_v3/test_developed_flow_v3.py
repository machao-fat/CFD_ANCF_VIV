import csv
import hashlib
import json
import math
import unittest
from pathlib import Path

from src.coupling.stage4d_campaign.developed_flow import canonical_sha, sha256_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = PROJECT_ROOT / "results" / "06_developed_flow_v3"
V2_ROOT = PROJECT_ROOT / "results" / "06_developed_flow_v2"
V2_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v2"
V3_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v3"
SNAPSHOT_TOL_S = 0.00125


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class DevelopedFlowV3ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summaries = {flow_id: read_json(RESULT_ROOT / flow_id / "flow_summary_v3.json") for flow_id in ("re80", "re100", "re120")}
        cls.bank = read_json(RESULT_ROOT / "developed_flow_bank_v3.json")
        cls.process = read_json(RESULT_ROOT / "process_limiter_real_overlap_v3_audit.json")
        cls.source_audit = read_json(RESULT_ROOT / "source_hash_audit_v3.json")

    def test_protocol_and_flow_ids_are_frozen(self):
        contract = read_json(PROJECT_ROOT / "results" / "05_stage4c_scalability_tests" / "canonical_3slice_manifest_candidate.json")
        self.assertEqual(contract["schema_version"], "0.2.1")
        self.assertEqual(contract["slice_manifest_sha256"], "d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3")
        self.assertEqual(self.bank["flow_ids"], ["re80", "re100", "re120"])

    def test_source_hash_audit_passed_and_v1_v2_unchanged(self):
        self.assertEqual(self.source_audit["status"], "passed")
        self.assertTrue(self.source_audit["v1_v2_evidence_unchanged"])
        for flow_id in ("re80", "re100", "re120"):
            self.assertEqual(self.source_audit["v1"][flow_id]["field_audit"]["status"], "passed")
            self.assertEqual(self.source_audit["v2"][flow_id]["audit"]["status"], "passed")

    def test_three_flows_have_expected_reynolds_numbers(self):
        expected = {"re80": (0.8, 80.0), "re100": (1.0, 100.0), "re120": (1.2, 120.0)}
        for flow_id, (velocity, reynolds) in expected.items():
            self.assertEqual(self.summaries[flow_id]["U_mps"], velocity)
            self.assertEqual(self.summaries[flow_id]["Re"], reynolds)
            self.assertEqual(self.summaries[flow_id]["physical_identity"]["dt_s"], 0.0025)

    def test_all_flows_are_developed_and_snapshot_aligned(self):
        for summary in self.summaries.values():
            self.assertEqual(summary["status"], "developed")
            self.assertLessEqual(abs(summary["snapshot_time_s"] - summary["statistics_end_time_s"]), SNAPSHOT_TOL_S)
            self.assertLessEqual(summary.get("force_snapshot_time_error_s", 0.0), SNAPSHOT_TOL_S)

    def test_snapshot_times_are_actual_field_endpoints(self):
        self.assertAlmostEqual(self.summaries["re80"]["snapshot_time_s"], 315.0, delta=SNAPSHOT_TOL_S)
        self.assertAlmostEqual(self.summaries["re100"]["snapshot_time_s"], 188.5, delta=SNAPSHOT_TOL_S)
        self.assertAlmostEqual(self.summaries["re120"]["snapshot_time_s"], 139.5, delta=SNAPSHOT_TOL_S)
        for flow_id, summary in self.summaries.items():
            case = V3_CASE_ROOT / flow_id if flow_id == "re80" else V2_CASE_ROOT / flow_id
            for relative_path, expected_hash in summary["final_fields"].items():
                self.assertEqual(sha256_file(case / relative_path), expected_hash, flow_id)

    def test_fixed_solver_parameters_are_preserved(self):
        for summary in self.summaries.values():
            self.assertEqual(summary["physical_identity"]["nu_m2ps"], 0.01)
            self.assertEqual(summary["physical_identity"]["rho_kgpm3"], 1000.0)
            self.assertEqual(summary["physical_identity"]["D_m"], 1.0)
            self.assertEqual(summary["physical_identity"]["dt_s"], 0.0025)

    def test_cfl_and_mesh_evidence(self):
        for flow_id, summary in self.summaries.items():
            self.assertIsNotNone(summary["max_cfl"], flow_id)
            self.assertLessEqual(float(summary["max_cfl"]), 0.8)
            self.assertEqual(summary["checkMesh"]["return_code"], 0)

    def test_statistics_have_two_complete_windows(self):
        for summary in self.summaries.values():
            stats = summary["statistics"]
            self.assertTrue(stats["window_1"]["available"])
            self.assertTrue(stats["window_2"]["available"])
            self.assertGreaterEqual(stats["window_1"]["complete_cycles"], 2.0)
            self.assertGreaterEqual(stats["window_2"]["complete_cycles"], 2.0)

    def test_stability_thresholds(self):
        for summary in self.summaries.values():
            stats = summary["statistics"]
            self.assertTrue(stats["all_stable_criteria"])
            self.assertLessEqual(stats["window_relative_changes"]["mean_Cd"], 0.03)
            self.assertLessEqual(stats["window_relative_changes"]["Cl_fluctuation_RMS"], 0.05)
            self.assertLessEqual(stats["window_relative_changes"]["frequency"], 0.03)
            self.assertGreaterEqual(stats["St"], 0.12)
            self.assertLessEqual(stats["St"], 0.22)

    def test_coefficients_are_finite_and_bounded(self):
        for flow_id, summary in self.summaries.items():
            stats = summary["statistics"]
            for key in ("St", "dominant_frequency_Hz"):
                self.assertTrue(math.isfinite(float(stats[key])), flow_id)
            for window_key in ("window_1", "window_2"):
                for key in ("mean_Cd", "Cd_rms", "Cl_rms", "Cl_peak_to_peak"):
                    value = float(stats[window_key][key])
                    self.assertTrue(math.isfinite(value), (flow_id, key))
                    self.assertLess(abs(value), 10.0)

    def test_re80_real_continuation_reached_beyond_v2_and_within_cap(self):
        summary = self.summaries["re80"]
        self.assertGreater(summary["snapshot_time_s"], summary["source_v2_snapshot_time_s"])
        self.assertLessEqual(summary["snapshot_time_s"], 360.0 + SNAPSHOT_TOL_S)
        self.assertGreaterEqual(summary["continuous_stable_evaluation_count"], 3)
        self.assertGreaterEqual(len(summary["solver_runs"]), 1)

    def test_re80_continuation_has_no_setfields_and_uses_latest_time(self):
        lineage = read_json(RESULT_ROOT / "re80" / "continuation_lineage_v3.json")
        self.assertFalse(lineage["setFields_called"])
        self.assertEqual(lineage["startFrom"], "latestTime")
        self.assertTrue(lineage["copied_only_same_re_source"])
        self.assertTrue(lineage["source_v2_unchanged"])

    def test_re80_solver_runs_completed_normally(self):
        summary = self.summaries["re80"]
        for run in summary["solver_runs"]:
            self.assertEqual(run["return_code"], 0)
            log_path = Path(run["log"])
            self.assertTrue(log_path.is_file())
            self.assertIn("End", log_path.read_text(encoding="utf-8", errors="replace"))

    def test_re80_continuation_force_hash_is_reproducible(self):
        summary = self.summaries["re80"]
        self.assertEqual(sha256_file(Path(summary["force_history_merged_v3_csv"])), summary["force_history_merged_v3_sha256"])
        self.assertEqual(summary["force_history_merged_v3_sha256"], read_json(RESULT_ROOT / "re80" / "continuation_lineage_v3.json")["continuation_force_sha256"])

    def test_re100_re120_use_truncated_force_histories(self):
        for flow_id in ("re100", "re120"):
            summary = self.summaries[flow_id]
            self.assertTrue(Path(summary["truncated_force_history_v3_csv"]).is_file())
            self.assertEqual(sha256_file(Path(summary["truncated_force_history_v3_csv"])), summary["truncated_force_history_v3_sha256"])
            alignment = read_json(RESULT_ROOT / flow_id / "snapshot_alignment_v3.json")
            self.assertEqual(alignment["source_v2_unchanged"], True)
            self.assertLessEqual(alignment["force_snapshot_time_error_s"], SNAPSHOT_TOL_S)

    def test_force_times_are_monotonic_and_finite(self):
        for flow_id, summary in self.summaries.items():
            path = Path(summary.get("force_history_merged_v3_csv", summary.get("truncated_force_history_v3_csv")))
            previous = -math.inf
            count = 0
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    time_s = float(row["time_s"])
                    force_x = float(row["force_x_N"])
                    force_y = float(row["force_y_N"])
                    self.assertGreaterEqual(time_s, previous, flow_id)
                    self.assertTrue(math.isfinite(time_s) and math.isfinite(force_x) and math.isfinite(force_y))
                    previous = time_s
                    count += 1
            self.assertGreater(count, 100, flow_id)

    def test_all_evaluations_are_real_solver_evaluations(self):
        convergence = read_json(RESULT_ROOT / "re80" / "convergence_history_v3.json")
        self.assertGreaterEqual(len(convergence["evaluations"]), 3)
        self.assertTrue(all(item["real_solver_evaluation"] for item in convergence["evaluations"]))
        self.assertTrue(all("fit" not in json.dumps(item).lower() for item in convergence["evaluations"]))

    def test_process_limiter_v3_provenance(self):
        self.assertEqual(self.process["status"], "passed")
        self.assertEqual(self.process["max_processes"], 2)
        self.assertLessEqual(self.process["peak_active_count"], 2)
        self.assertLessEqual(self.process["interval_peak_active_count"], 2)
        self.assertFalse(self.process["permit_leak"])
        self.assertEqual(len(self.process["fresh_overlap_smoke"]["records"]), 3)
        self.assertTrue(all(item["setFields_called"] for item in self.process["fresh_overlap_smoke"]["records"]))
        self.assertTrue(all(not item["setFields_called"] for item in self.process["continuation_cases"]))

    def test_process_intervals_recompute_peak(self):
        intervals = [(int(item["start_time_ns"]), int(item["end_time_ns"])) for item in self.process["intervals"]]
        events = []
        for start, end in intervals:
            self.assertLess(start, end)
            events.append((start, 1))
            events.append((end, -1))
        active = peak = 0
        for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
            active += delta
            peak = max(peak, active)
        self.assertEqual(peak, self.process["interval_peak_active_count"])
        self.assertLessEqual(peak, 2)

    def test_fresh_process_logs_have_successful_setfields(self):
        for item in self.process["fresh_overlap_smoke"]["records"]:
            self.assertEqual(item["setFields_return_code"], 0)
            self.assertTrue(item["case_log_path_match"])
            self.assertEqual(sha256_file(Path(item["setFields_log"])), item["setFields_log_sha256"])

    def test_bank_hash_and_status_are_reproducible(self):
        identity = [
            {
                "flow_id": item["flow_id"],
                "U_mps": item["U_mps"],
                "Re": item["Re"],
                "snapshot_time_s": item["snapshot_time_s"],
                "statistics_end_time_s": item["statistics_end_time_s"],
                "developed_flow_sha256": item["developed_flow_sha256"],
                "force_sha256": item.get("force_history_merged_v3_sha256", item.get("truncated_force_history_v3_sha256")),
                "final_fields": item["final_fields"],
            }
            for item in self.summaries.values()
        ]
        self.assertEqual(self.bank["status"], "ready_for_sol_review")
        self.assertEqual(self.bank["developed_flow_bank_sha256"], canonical_sha(identity))
        self.assertTrue(self.bank["bank_identity_excludes_absolute_paths"])

    def test_bank_contains_source_lineage_for_each_flow(self):
        self.assertEqual([item["flow_id"] for item in self.bank["source_lineage"]], ["re80", "re100", "re120"])
        for item in self.bank["source_lineage"]:
            self.assertTrue(item["lineage_artifact"])
            self.assertTrue(item["source_v2_developed_flow_sha256"])
            self.assertTrue(item["source_v2_force_sha256"])
            self.assertFalse(item["setFields_called"])

    def test_physical_identity_hashes_exclude_absolute_paths(self):
        for summary in self.summaries.values():
            identity_text = json.dumps(summary["physical_identity"], ensure_ascii=False)
            self.assertNotIn("D:\\", identity_text)
            self.assertNotIn("/results/", identity_text)
            self.assertEqual(summary["developed_flow_sha256"], canonical_sha(summary["physical_identity"]))


if __name__ == "__main__":
    unittest.main()
