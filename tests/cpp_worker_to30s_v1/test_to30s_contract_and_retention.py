from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coupling.cpp_worker_confirm_v1.contracts import CppConfirmContract, ContractError
from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as runner


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/cpp_worker_to6s_v1/to6s_001/checkpoint/checkpoint_00003593.json"


class To30sContractAndRetentionTests(unittest.TestCase):
    def test_stage214_portable_source_and_first_target_identity(self) -> None:
        payload = json.loads(SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(payload["global_step"], 3593)
        self.assertEqual(payload["time_s"], 6.0)
        self.assertEqual(payload["integer_tick"], 6_000_000_000)
        state = payload["checkpoint_metadata"]["ancf_restart_state"]
        self.assertEqual(state["global_step"], 3593)
        self.assertEqual(state["state_sha256"], "d805b501450797ab937d2eba0720373f9c9f905ad8a3f3f02a028665360ab31c")
        self.assertEqual((3593 + 1, 1, 6.00125, 6_001_250_000), (3594, 1, 6.00125, 6_001_250_000))

    def test_exact_to30s_contract_is_accepted_and_scope_mutation_is_rejected(self) -> None:
        contract = CppConfirmContract(
            stage_id="stage4f_d_cpp_worker_to30s_v1", run_id="offline_to30s", case_id="offline_case",
            runtime=ROOT / "runtime/cpp_worker_to30s_v1/offline", results=ROOT / "results/215_offline",
            source_checkpoint=SOURCE, source_checkpoint_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            source_global_step=3593, source_time_s=6.0, source_tick=6_000_000_000,
            steps=19_200, segment_duration_s=24.0,
        )
        contract.validate(ROOT)
        with self.assertRaises(ContractError):
            CppConfirmContract(**{**contract.__dict__, "steps": 19_201, "segment_duration_s": 24.00125}).validate(ROOT)

    def test_durable_journal_precedes_exact_middle_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"; results = root / "results"; journal = results / "compact_step_journal.jsonl"
            for parent in (runtime / "checkpoint", runtime / "commit_journal"):
                parent.mkdir(parents=True)
                name = "checkpoint_00003594.json" if parent.name == "checkpoint" else "commit_00003594.json"
                (parent / name).write_text("{}\n", encoding="utf-8")
            for sid in range(3):
                field = runtime / "cases" / f"slice_{sid:04d}" / "6.00125"
                field.mkdir(parents=True); (field / "U").write_text("field\n", encoding="utf-8")
            with mock.patch.object(runner, "RUNTIME", runtime), mock.patch.object(runner, "SOURCE_GLOBAL_STEP", 3593), mock.patch.object(runner, "SOURCE_TIME_S", 6.0), mock.patch.object(runner, "SPARSE_RETENTION", True), mock.patch.object(runner, "SPARSE_KEEP_FULL_STEPS", 40):
                with self.assertRaises(RuntimeError):
                    runner._evict_sparse_step(global_step=3634, journal_path=journal)
                runner._append_jsonl_durable(journal, {"global_step": 3634})
                removed = runner._evict_sparse_step(global_step=3634, journal_path=journal)
            self.assertEqual(len(removed), 5)
            self.assertFalse((runtime / "checkpoint/checkpoint_00003594.json").exists())
            self.assertFalse((runtime / "commit_journal/commit_00003594.json").exists())
            self.assertTrue(journal.is_file())

    def test_count_only_records_preserve_scope_without_payload_retention(self) -> None:
        records = runner._CountOnlyRecords()
        records.append({"large": "x" * 1_000_000})
        self.assertEqual(len(records), 1)
        self.assertFalse(hasattr(records, "records"))


if __name__ == "__main__":
    unittest.main()
