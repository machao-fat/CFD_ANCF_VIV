from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_c_strong_coupling_preflight_v1.coordinator import (
    CheckpointIdentity,
    OuterFixedPointCoordinator,
    PromotionReceipt,
    StrongCouplingProtocolError,
    TrialObservation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metrics(**updates):
    value = {
        "max_abs_Cd": 6.0,
        "max_CFL": 0.2,
        "position_difference_over_D": 0.001,
        "velocity_difference_over_U": 0.001,
        "virtual_work_relative_error": 1.0e-14,
        "force_conversion_relative_error": 0.0,
        "all_three_slices_complete": True,
        "rollback_verified": True,
        "fatal_detected": False,
        "negative_volume_detected": False,
    }
    value.update(updates)
    return value


class _Harness:
    def __init__(self, root: Path, *, fault: str | None = None, observed_force: float = 10.0):
        self.root = root
        self.fault = fault
        self.observed_force = observed_force
        self.promotions = []
        self.parent_file = root / "parent.json"
        self.parent_file.write_text("parent", encoding="ascii")
        self.parent = CheckpointIdentity(self.parent_file, _sha(self.parent_file), source_physical_step=2)

    def executor(self, request):
        parent_path = request.parent.path
        parent_hash = request.parent.sha256
        physical_step = request.physical_step
        target_tick = request.target_tick_ns
        if self.fault == "wrong_parent":
            parent_hash = "0" * 64
        if self.fault == "wrong_parent_path":
            parent_path = self.root / "other.json"
        if self.fault == "wrong_time":
            target_tick += 1
        if self.fault == "wrong_step":
            physical_step += 1
        return TrialObservation(
            rollback_checkpoint_sha256=parent_hash,
            rollback_source_path=parent_path,
            physical_step=physical_step,
            strong_iteration=request.strong_iteration,
            inner_iteration=0,
            current_tick_ns=request.current_tick_ns,
            target_tick_ns=target_tick,
            observed_force_N=[[self.observed_force, 0.0, 0.0]] * 3,
            metrics=_metrics(),
            trial_checkpoint_committed=self.fault == "trial_committed",
            partial_cfd_failure=self.fault == "partial_cfd_failure",
        )

    def promoter(self, request):
        self.promotions.append(request)
        target = self.root / f"commit_step{request.physical_step}.json"
        target.write_text(f"commit {request.physical_step}", encoding="ascii")
        stored = request.observed_force_N
        if self.fault == "relaxed_as_observed":
            stored = request.relaxed_force_N
        if self.fault == "wrong_promoted_step":
            source_step = request.physical_step + 1
        else:
            source_step = request.physical_step
        return PromotionReceipt(
            checkpoint=CheckpointIdentity(target, _sha(target), source_step),
            physical_step=request.physical_step,
            target_tick_ns=request.target_tick_ns,
            selected_strong_iteration=request.selected_strong_iteration,
            stored_observed_force_N=stored,
        )

    def coordinator(self):
        return OuterFixedPointCoordinator(initial_parent=self.parent, initial_force_N=[[0.0, 0.0, 0.0]] * 3)


class OuterFixedPointCoordinatorTests(unittest.TestCase):
    def test_three_stage_local_steps_commit_once_each_with_exact_ticks(self):
        with tempfile.TemporaryDirectory() as raw:
            harness = _Harness(Path(raw))
            coordinator = harness.coordinator()
            results = coordinator.run_three_step_preflight(harness.executor, harness.promoter)
            self.assertEqual([row.status for row in results], ["committed", "committed", "committed"])
            self.assertEqual([row.physical_step for row in results], [0, 1, 2])
            self.assertEqual([row.target_tick_ns for row in results], [1_508_125_000, 1_508_750_000, 1_509_375_000])
            self.assertEqual(len(harness.promotions), 3)
            self.assertTrue(all(len(row.iterations) == 2 for row in results))
            self.assertEqual(coordinator.parent.source_physical_step, 2)

    def test_wrong_time_or_step_blocks_zero_promotion(self):
        for fault in ("wrong_time", "wrong_step"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as raw:
                harness = _Harness(Path(raw), fault=fault)
                result = harness.coordinator().run_physical_step(0, harness.executor, harness.promoter)
                self.assertEqual(result.status, "failed")
                self.assertEqual(harness.promotions, [])

    def test_trial_commit_is_rejected_before_promotion(self):
        with tempfile.TemporaryDirectory() as raw:
            harness = _Harness(Path(raw), fault="trial_committed")
            result = harness.coordinator().run_physical_step(0, harness.executor, harness.promoter)
            self.assertEqual(result.status, "failed")
            self.assertIn("committed a checkpoint", result.failure_reason)
            self.assertEqual(harness.promotions, [])

    def test_single_step_cannot_receive_multiple_promotions(self):
        with tempfile.TemporaryDirectory() as raw:
            harness = _Harness(Path(raw))
            coordinator = harness.coordinator()
            self.assertEqual(coordinator.run_physical_step(0, harness.executor, harness.promoter).status, "committed")
            with self.assertRaises(StrongCouplingProtocolError):
                coordinator.run_physical_step(0, harness.executor, harness.promoter)
            self.assertEqual(len(harness.promotions), 1)

    def test_relaxed_force_cannot_be_promoted_as_observed_force(self):
        with tempfile.TemporaryDirectory() as raw:
            harness = _Harness(Path(raw), fault="relaxed_as_observed")
            result = harness.coordinator().run_physical_step(0, harness.executor, harness.promoter)
            self.assertEqual(result.status, "failed")
            self.assertIn("relaxed force", result.failure_reason)

    def test_wrong_rollback_parent_identity_blocks_step(self):
        for fault in ("wrong_parent", "wrong_parent_path"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as raw:
                harness = _Harness(Path(raw), fault=fault)
                result = harness.coordinator().run_physical_step(0, harness.executor, harness.promoter)
                self.assertEqual(result.status, "failed")
                self.assertEqual(harness.promotions, [])

    def test_nonconvergence_has_zero_promotions_and_blocks_following_step(self):
        with tempfile.TemporaryDirectory() as raw:
            harness = _Harness(Path(raw), observed_force=100_000.0)
            coordinator = harness.coordinator()
            result = coordinator.run_physical_step(0, harness.executor, harness.promoter)
            self.assertEqual(result.status, "failed")
            self.assertEqual(len(result.iterations), 12)
            self.assertEqual(harness.promotions, [])
            with self.assertRaises(StrongCouplingProtocolError):
                coordinator.run_physical_step(1, harness.executor, harness.promoter)

    def test_partial_cfd_failure_blocks_zero_promotion(self):
        with tempfile.TemporaryDirectory() as raw:
            harness = _Harness(Path(raw), fault="partial_cfd_failure")
            result = harness.coordinator().run_physical_step(0, harness.executor, harness.promoter)
            self.assertEqual(result.status, "failed")
            self.assertIn("partial CFD", result.failure_reason)
            self.assertEqual(harness.promotions, [])

    def test_promotion_must_identify_selected_physical_step(self):
        with tempfile.TemporaryDirectory() as raw:
            harness = _Harness(Path(raw), fault="wrong_promoted_step")
            result = harness.coordinator().run_physical_step(0, harness.executor, harness.promoter)
            self.assertEqual(result.status, "failed")
            self.assertIn("source physical step", result.failure_reason)

    def test_restart_source_path_and_hash_are_verified(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            missing = CheckpointIdentity(root / "missing.json", "a" * 64, source_physical_step=2)
            with self.assertRaisesRegex(StrongCouplingProtocolError, "path"):
                OuterFixedPointCoordinator(initial_parent=missing, initial_force_N=[[0, 0, 0]] * 3)
            harness = _Harness(root)
            harness.parent_file.write_text("tampered", encoding="ascii")
            with self.assertRaisesRegex(StrongCouplingProtocolError, "SHA-256"):
                harness.coordinator()


if __name__ == "__main__":
    unittest.main()

