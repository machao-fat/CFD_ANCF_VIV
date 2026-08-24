import json
import unittest
from pathlib import Path

from src.coupling.multi_slice_mapping.mapping import RuntimeConfig, SliceManifest


ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2_1"


def load(name):
    return json.loads((RESULT / name).read_text(encoding="utf-8"))


class Stage4FCloseoutTests(unittest.TestCase):
    def test_candidate_local_rejection_and_selected_candidate(self):
        selected = load("selected_structure_candidate_v2_1.json")
        self.assertEqual(selected["selected_candidate"]["mass_ratio"], 5)
        self.assertEqual(selected["selected_candidate"]["beta"], 0.01)
        self.assertTrue(selected["selected_static_nElem32"]["passes"])
        self.assertEqual(selected["rejected_candidates"][0]["mass_ratio"], 10)
        self.assertGreater(selected["rejected_candidates"][0]["negative_tension_fraction"], 0.01)

    def test_protocol_identities_are_formal(self):
        for label, count in (("three", 3), ("five", 5), ("nine", 9)):
            artifact = load(f"{label}_slice_protocol_0_2_1.json")
            manifest = SliceManifest.from_mapping(artifact["manifest"])
            config = RuntimeConfig.from_mapping(artifact["runtime_config"])
            config.validate_against_manifest(manifest)
            self.assertEqual(len(manifest.slices), count)
            self.assertAlmostEqual(sum(item.slice_length_m for item in manifest.slices), 50.0, places=12)

    def test_conservation_and_readonly_audit(self):
        gate = load("stage4f_a_v2_1_gate_candidate.json")
        audit = load("v2_evidence_readonly_hash_audit.json")
        virtual = load("virtual_work_audit.json")
        self.assertTrue(gate["gate_passed"])
        self.assertEqual(audit["status"], "passed")
        self.assertLessEqual(virtual["maximum_absolute_or_relative_error"], 1e-12)


if __name__ == "__main__":
    unittest.main()
