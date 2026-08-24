import json
import math
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "08_stage4e_physical_baseline"
RAW = RESULTS / "ancf_design_raw.json"


def load_json(name):
    with (RESULTS / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def assert_finite_tree(testcase, value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            assert_finite_tree(testcase, child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_finite_tree(testcase, child, f"{path}[{index}]")
    elif isinstance(value, float):
        testcase.assertTrue(math.isfinite(value), path)


class Stage4EAOfflineTests(unittest.TestCase):
    def test_required_artifacts_and_offline_scope(self):
        required = [
            "source_inventory.json",
            "benchmark_candidate_matrix.json",
            "vivdatashare_audit.json",
            "duanmu_method_audit.json",
            "selected_primary_benchmark.json",
            "selected_fallback_benchmark.json",
            "dimensionless_parameter_mapping.json",
            "ancf_structural_design.json",
            "ancf_mesh_convergence.json",
            "cost_estimate.json",
            "stage4e_a_candidate_summary.json",
        ]
        for name in required:
            self.assertTrue((RESULTS / name).is_file(), name)
        summary = load_json("stage4e_a_candidate_summary.json")
        self.assertFalse(summary["real_cfd_started"])
        self.assertEqual(summary["status"], "partially_completed")

    def test_protocol_and_manifest_identity_are_frozen(self):
        contract = (ROOT / "docs" / "05_multi_slice_contract.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("0.2.1", contract)
        manifest = (
            ROOT
            / "results"
            / "05_stage4c_scalability_tests"
            / "canonical_3slice_manifest_candidate.json"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3",
            manifest,
        )

    def test_public_source_hash_and_license_boundary_are_recorded(self):
        inventory = load_json("source_inventory.json")
        viv = next(
            record
            for record in inventory["public_sources"]
            if record["id"] == "vivdatashare_experiment_csv"
        )
        self.assertEqual(
            viv["sha256"],
            "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df",
        )
        audit = load_json("vivdatashare_audit.json")
        self.assertFalse(audit["observed_public_tree"]["license_file_found"])
        self.assertTrue(audit["blocking_items_for_formal_primary"])

    def test_dimensionless_mapping_reproduces_reference_values(self):
        mapping = load_json("dimensionless_parameter_mapping.json")
        project = mapping["frozen_project"]
        re100 = next(item for item in project["Re_by_slice_with_nu_0p01"] if item["U_mps"] == 1.0)
        st100 = next(item for item in project["existing_developed_flow"] if item["U_mps"] == 1.0)
        self.assertAlmostEqual(re100["Re"], 100.0, places=12)
        self.assertAlmostEqual(st100["St_from_existing_bank"], 0.14149994022481596, places=12)
        candidate = mapping["public_candidate"]
        self.assertAlmostEqual(candidate["Re_at_Umax_if_nu_1e-6"], 13636.8, places=8)

    def test_ancf_results_are_finite_and_mesh_boundary_is_explicit(self):
        raw = json.loads(RAW.read_text(encoding="utf-8"))
        assert_finite_tree(self, raw)
        mesh = load_json("ancf_mesh_convergence.json")
        pairs = [configuration["adjacent_pairs"] for configuration in mesh["configurations"]]
        pair_4_8 = [next(pair for pair in items if pair["coarse_nElem"] == 4) for items in pairs]
        for pair in pair_4_8:
            self.assertTrue(pair["major_modes_pass_2pct"])
            self.assertFalse(pair["all_mode_1pct_pass"])
        self.assertIn("strict", mesh["conclusion"].lower())

    def test_no_real_solver_case_was_created_by_stage4e(self):
        allowed_cases = ROOT / "cases" / "openfoam"
        marker = re.compile(r"stage4e", re.IGNORECASE)
        if allowed_cases.exists():
            created = [path for path in allowed_cases.iterdir() if marker.search(path.name)]
            self.assertEqual(created, [], "Stage 4E-A must not create OpenFOAM cases")


if __name__ == "__main__":
    unittest.main()
