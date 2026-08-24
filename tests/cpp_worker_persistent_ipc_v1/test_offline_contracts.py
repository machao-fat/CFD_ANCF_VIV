from __future__ import annotations

import unittest

from coupling.cpp_worker_persistent_ipc_v1.offline_contracts import (
    CheckpointAudit, GlobalBarrierMock, OwnershipAudit, SliceAck,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import FrameError


class OfflineContractTests(unittest.TestCase):
    def test_three_slice_barrier_releases_only_after_all_slices(self) -> None:
        barrier = GlobalBarrierMock()
        for slice_id in (0, 1):
            self.assertFalse(barrier.submit(SliceAck(slice_id, 560, 1, 2.20875, 2208750000, 100 + slice_id)))
        self.assertTrue(barrier.submit(SliceAck(2, 560, 1, 2.20875, 2208750000, 102)))
        self.assertEqual(barrier.released, [560])

    def test_barrier_rejects_stale_duplicate_and_wrong_tick(self) -> None:
        barrier = GlobalBarrierMock()
        with self.assertRaises(FrameError):
            barrier.submit(SliceAck(0, 559, 0, 2.2075, 2207500000, 1))
        barrier.submit(SliceAck(0, 560, 1, 2.20875, 2208750000, 1))
        with self.assertRaises(FrameError):
            barrier.submit(SliceAck(0, 560, 1, 2.20875, 2208750000, 1))
        with self.assertRaises(FrameError):
            barrier.submit(SliceAck(1, 560, 1, 2.20875, 2208750001, 2))

    def test_checkpoint_lineage_and_high_step_mapping(self) -> None:
        audit = CheckpointAudit()
        for bridge in range(1, 41):
            audit.commit(global_step=559 + bridge, case_local_bridge_step=bridge,
                         time_s=2.2075 + bridge * 0.00125, integer_tick=2207500000 + bridge * 1250000)
        self.assertEqual(len(audit.committed), 40)
        with self.assertRaises(FrameError):
            audit.commit(global_step=601, case_local_bridge_step=41, time_s=2.26, integer_tick=2260000000)

    def test_owned_process_close_is_exact(self) -> None:
        audit = OwnershipAudit(); audit.start(1234); audit.close(1234)
        self.assertEqual(audit.residual, 0)
        with self.assertRaises(FrameError):
            audit.close(9999)


if __name__ == "__main__":
    unittest.main()
