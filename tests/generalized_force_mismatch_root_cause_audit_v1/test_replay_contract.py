from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "generalized_force_mismatch_root_cause_audit_v1" / "replay.py"
spec = importlib.util.spec_from_file_location("generalized_force_replay", TOOL)
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class GeneralizedForceReplayContractTests(unittest.TestCase):
    def test_slice_location_matches_reference_partition(self) -> None:
        self.assertEqual(replay.location(8.333333333333334, 50.0, 16)["element_index_0_based"], 2)
        self.assertEqual(replay.location(25.0, 50.0, 16)["element_index_0_based"], 8)
        self.assertEqual(replay.location(41.666666666666664, 50.0, 16)["element_index_0_based"], 13)

    def test_replay_uses_integrated_forces_without_second_scaling(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn('"force_representation": "integrated_slice_force_N"', source)
        self.assertIn("Passing\n    # bare vectors deliberately prevents a second unit-span/tributary-length", source)

    def test_failed_runtime_has_no_step10_replay_fixture(self) -> None:
        rows = [json.loads(line) for line in (ROOT / "runtime" /
                "moving_mesh_patch_consistency_1s_retry_v1_run_001" / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["global_step"] for row in rows], list(range(1, 10)))
        self.assertFalse((ROOT / "runtime" / "moving_mesh_patch_consistency_1s_retry_v1_run_001" /
                          "correction_attempts.jsonl").exists())

    def test_future_attempt_writer_precedes_generalized_force_gate(self) -> None:
        source = (ROOT / "tools" / "three_slice_force_contract_smoke_v1" /
                  "structure_participant.py").read_text(encoding="utf-8")
        self.assertLess(source.index('append_jsonl(runtime / "correction_attempts.jsonl", attempt)'),
                        source.index('raise RuntimeError("C++ generalized force fails formal H^T mapping metric V2")'))

    def test_precpp_evidence_precedes_worker_correction(self) -> None:
        source = (ROOT / "tools" / "three_slice_force_contract_smoke_v1" /
                  "structure_participant.py").read_text(encoding="utf-8")
        self.assertLess(source.index('append_jsonl(runtime / "correction_attempts_pre_cpp.jsonl", pre_cpp_attempt)'),
                        source.index('correction, _ = adapter.correct(step, time_s, [item.force_N for item in loads])'))


if __name__ == "__main__":
    unittest.main()
