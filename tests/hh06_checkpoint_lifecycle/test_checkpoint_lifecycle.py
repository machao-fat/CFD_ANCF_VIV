"""Offline regression tests for one-window checkpoint lifetime semantics.

These tests exercise only :class:`GenericStructuralCoordinator` with a small
deterministic backend.  They do not import preCICE, start a worker, or advance
OpenFOAM/ANCF physical time.
"""

from __future__ import annotations

import copy
import unittest

from src.coupling.arbitrary_n_live_orchestration_v1.coordinator import (
    CheckpointError,
    ForceSample,
    GenericStructuralCoordinator,
    WorkerRequest,
)
from src.coupling.arbitrary_n_live_orchestration_v1.manifest import (
    OrchestrationSlice,
    SliceManifest,
)


class _TransportAwareBackend:
    """Deterministic backend whose transport IDs are not checkpointed."""

    def __init__(self) -> None:
        self.q = [0.0, 0.0, 0.0]
        self.qdot = [0.0, 0.0, 0.0]
        self.qddot = [0.0, 0.0, 0.0]
        self.pending = False
        self.transport_sequence = 0
        self.transport_request = 0
        self.transport_transaction = 0
        self.requests: list[tuple[int, float]] = []

    def snapshot(self):
        # Transport identity deliberately does not belong to the physical
        # checkpoint.  It must remain monotonic after restore/retry.
        return {
            "q": list(self.q),
            "qdot": list(self.qdot),
            "qddot": list(self.qddot),
            "pending": self.pending,
        }

    def restore(self, snapshot):
        self.q = list(snapshot["q"])
        self.qdot = list(snapshot["qdot"])
        self.qddot = list(snapshot["qddot"])
        self.pending = bool(snapshot["pending"])

    def advance(self, request: WorkerRequest):
        self.transport_sequence += 1
        self.transport_request += 1
        self.transport_transaction += 1
        self.requests.append((request.iteration, request.time_s))
        self.q = [value + 0.25 for value in self.q]
        self.qdot = [value + 0.5 for value in self.qdot]
        self.qddot = [value + 0.75 for value in self.qddot]
        self.pending = True
        return {
            "sequence": self.transport_sequence,
            "request_id": self.transport_request,
            "transaction_id": self.transport_transaction,
        }

    def commit(self):
        if not self.pending:
            raise AssertionError("commit without a tentative advance")
        self.pending = False

    def evaluate_position(self, _s_ref_m: float):
        return (self.q[0], self.q[1], self.q[2])


def _manifest() -> SliceManifest:
    item = OrchestrationSlice(
        slice_id="slice_0000",
        ordinal=0,
        s_ref_m=1.0,
        slice_length_m=1.0,
        unit_span_m=1.0,
        fluid_participant="Fluid_slice_0000",
        structure_participant="Structure_0000",
        structure_mesh="Structure-Mesh-slice_0000",
        fluid_mesh="Fluid-Mesh-slice_0000",
        force_data="Force",
        motion_data="Displacement",
        openfoam_case_id="hh06",
        force_slot=0,
        motion_slot=0,
    )
    return SliceManifest(
        schema_version="arbitrary-n-live-coupling-v1",
        case_id="hh06_checkpoint_test",
        reference_length_m=2.0,
        active_start_m=0.0,
        active_end_m=2.0,
        reconstruction_mode="LegacyPointLumped",
        endpoint_policy="NearestConstant",
        structure_participant="Structure_0000",
        slices=(item,),
    )


def _force(manifest: SliceManifest) -> ForceSample:
    return ForceSample.from_openfoam_integrated(
        manifest,
        "slice_0000",
        iteration=0,
        time_s=0.0002,
        force_N=(1.0, 0.0, 0.0),
        unit_span_m=1.0,
    )


def _advance(coordinator: GenericStructuralCoordinator, sample: ForceSample):
    coordinator.submit_force(sample)
    result = coordinator.advance_if_complete()
    coordinator.scatter_motion()
    return result


class CheckpointLifecycleTests(unittest.TestCase):
    def test_rollback_once_restores_exact_state_and_keeps_checkpoint(self):
        backend = _TransportAwareBackend()
        coordinator = GenericStructuralCoordinator(_manifest(), backend)
        initial = (copy.deepcopy(backend.q), copy.deepcopy(backend.qdot), copy.deepcopy(backend.qddot))
        coordinator.checkpoint("window-1")
        first = _advance(coordinator, _force(coordinator.manifest))
        trial_state = (backend.q, backend.qdot, backend.qddot)
        coordinator.rollback()
        self.assertEqual((backend.q, backend.qdot, backend.qddot), initial)
        self.assertIsNotNone(coordinator._checkpoint)
        self.assertNotEqual(trial_state, initial)
        self.assertEqual(first["sequence"], 1)

    def test_two_rollbacks_in_one_window_reuse_same_checkpoint(self):
        backend = _TransportAwareBackend()
        coordinator = GenericStructuralCoordinator(_manifest(), backend)
        initial = (list(backend.q), list(backend.qdot), list(backend.qddot))
        coordinator.checkpoint("window-1")
        sample = _force(coordinator.manifest)
        first = _advance(coordinator, sample)
        coordinator.rollback()
        second = _advance(coordinator, sample)
        coordinator.rollback()
        self.assertEqual((backend.q, backend.qdot, backend.qddot), initial)
        self.assertIsNotNone(coordinator._checkpoint)
        self.assertEqual([first["sequence"], second["sequence"]], [1, 2])
        self.assertEqual([first["request_id"], second["request_id"]], [1, 2])
        self.assertEqual([first["transaction_id"], second["transaction_id"]], [1, 2])
        self.assertIsNone(coordinator.last_request)

    def test_rollback_retry_commit_clears_checkpoint_only_after_commit(self):
        backend = _TransportAwareBackend()
        coordinator = GenericStructuralCoordinator(_manifest(), backend)
        coordinator.checkpoint("window-1")
        sample = _force(coordinator.manifest)
        first = _advance(coordinator, sample)
        coordinator.rollback()
        second = _advance(coordinator, sample)
        retry_state = (list(backend.q), list(backend.qdot), list(backend.qddot))
        coordinator.commit()
        self.assertIsNone(coordinator._checkpoint)
        self.assertEqual((backend.q, backend.qdot, backend.qddot), retry_state)
        self.assertEqual(coordinator.committed_step, 1)
        self.assertGreater(second["sequence"], first["sequence"])
        self.assertGreater(second["request_id"], first["request_id"])
        self.assertGreater(second["transaction_id"], first["transaction_id"])
        with self.assertRaises(CheckpointError):
            coordinator.rollback()


if __name__ == "__main__":
    unittest.main()
