from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.multi_slice_driver import (
    MultiSliceConfig,
    MultiSliceScheduler,
    SchedulerError,
    SchedulerState,
    SliceSpec,
)
from src.coupling.multi_slice_driver.mocks import MockSliceProcess, MockStructureAdapter
from tests.multi_slice_driver.harness import make_harness


class MultiSliceOrchestrationTests(unittest.TestCase):
    def test_state_machine_two_slice_success_and_atomic_commit(self):
        scheduler, structure, processes, root = make_harness(n_slices=2)
        first = scheduler.run_step(step=0, time_s=0.0)
        second = scheduler.run_step(step=1, time_s=0.01)
        self.assertEqual(first.state, SchedulerState.COMMITTED)
        self.assertEqual(second.state, SchedulerState.COMMITTED)
        self.assertEqual(structure.committed_step, 1)
        self.assertEqual(structure.commit_count, 2)
        self.assertTrue(first.checkpoint_path.is_file())
        log_rows = [json.loads(line) for line in (root / "exchange" / "transaction_log.jsonl").read_text(encoding="utf-8").splitlines()]
        statuses = [row["status"] for row in log_rows if row["step"] == 0]
        for state in ("PREDICTED", "MOTION_PUBLISHED", "MOTION_CONSUMED", "CFD_ADVANCED", "LOADS_READY", "LOADS_CONSUMED", "STRUCTURE_CORRECTED", "CHECKPOINT_PREPARED", "COMMITTED"):
            self.assertIn(state, statuses)
        for process in processes:
            self.assertTrue((root / "exchange" / f"slice_{process.slice_id:04d}" / "consumed" / "load_step00000000_iter0000.consumed.json").is_file())

    def test_five_slice_success_uses_slice_id_order(self):
        scheduler, structure, processes, root = make_harness(n_slices=5)
        result = scheduler.run_step(step=0, time_s=0.0)
        self.assertEqual([row["slice_id"] for row in result.integrated_slice_forces], list(range(5)))
        self.assertEqual(structure.committed_step, 0)
        manifest = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["expected_slice_ids"], [0, 1, 2, 3, 4])
        self.assertEqual([entry["slice_id"] for entry in manifest["slices"]], [0, 1, 2, 3, 4])

    def test_missing_and_duplicate_slice_ids_rejected_before_transaction(self):
        specs = (SliceSpec(0, 0.0, 0.25), SliceSpec(1, 0.25, 0.25))
        config = MultiSliceConfig(case_id="case", dt_s=0.01, timeout_s=0.05, specs=specs)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            structure = MockStructureAdapter(specs)
            process0 = MockSliceProcess(specs[0], case_id="case", exchange_root=root / "exchange", case_root=root / "cases")
            with self.assertRaises(SchedulerError):
                MultiSliceScheduler(config=config, exchange_root=root / "exchange", structure=structure, slice_processes=[process0], checkpoint_root=root / "checkpoints", case_root=root / "cases")
            process0b = MockSliceProcess(specs[0], case_id="case", exchange_root=root / "exchange2", case_root=root / "cases2")
            process0c = MockSliceProcess(specs[0], case_id="case", exchange_root=root / "exchange2", case_root=root / "cases2")
            with self.assertRaises(SchedulerError):
                MultiSliceScheduler(config=config, exchange_root=root / "exchange2", structure=structure, slice_processes=[process0b, process0c], checkpoint_root=root / "checkpoints2", case_root=root / "cases2")

    def test_all_failure_injections_fail_closed_and_do_not_commit_structure(self):
        # 14 protocol/process failures plus 8 CFD checkpoint field failures,
        # followed by three ANCF state-field failures: 25 explicit checks.
        cases = [
            "missing_motion_consumed", "missing_load_ready", "wrong_time", "wrong_step", "early_step",
            "wrong_iteration", "payload_hash", "config_hash", "slice_manifest_hash",
            "nan", "inf", "timeout", "process_exit",
        ]
        for fault in cases:
            with self.subTest(fault=fault):
                scheduler, structure, processes, root = make_harness(n_slices=2, faults={1: fault}, timeout_s=0.02)
                with self.assertRaises(SchedulerError):
                    scheduler.run_step(step=0, time_s=0.0)
                self.assertEqual(scheduler.state, SchedulerState.FAILED)
                self.assertEqual(structure.committed_step, -1)
                self.assertEqual(structure.commit_count, 0)
                failure = root / "exchange" / "failure_step00000000.json"
                self.assertTrue(failure.is_file())
                self.assertFalse(list((root / "checkpoints").glob("checkpoint_*.json")))

        checkpoint_fields = ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "motionScale", "uniform/time")
        for field in checkpoint_fields:
            with self.subTest(checkpoint_field=field):
                scheduler, structure, processes, root = make_harness(n_slices=2, faults={1: f"checkpoint_missing_{field}"})
                with self.assertRaises(SchedulerError):
                    scheduler.run_step(step=0, time_s=0.0)
                self.assertEqual(structure.committed_step, -1)
                self.assertEqual(structure.commit_count, 0)

        for state_field in ("missing_checkpoint", "q", "qdot", "qddot"):
            with self.subTest(state_field=state_field):
                fault = state_field if state_field == "missing_checkpoint" else f"missing_{state_field}"
                scheduler, structure, processes, root = make_harness(n_slices=2, structure_fault=fault)
                with self.assertRaises(SchedulerError):
                    scheduler.run_step(step=0, time_s=0.0)
                self.assertEqual(structure.committed_step, -1)
                self.assertEqual(structure.commit_count, 0)

    def test_structure_correct_failure_does_not_advance_committed_state(self):
        scheduler, structure, processes, root = make_harness(n_slices=2, structure_fault="correct_failure")
        with self.assertRaises(SchedulerError):
            scheduler.run_step(step=0, time_s=0.0)
        self.assertEqual(structure.correct_calls, 1)
        self.assertEqual(structure.committed_step, -1)
        self.assertEqual(structure.commit_count, 0)

    def test_no_old_load_fallback(self):
        scheduler, structure, processes, root = make_harness(n_slices=2)
        scheduler.run_step(step=0, time_s=0.0)
        processes[1].fault = "missing_load_ready"
        with self.assertRaises(SchedulerError):
            scheduler.run_step(step=1, time_s=0.01)
        self.assertEqual(structure.committed_step, 0)
        self.assertFalse((root / "exchange" / "slice_0001" / "load" / "load_step00000001_iter0000.csv").is_file())


if __name__ == "__main__":
    unittest.main()
