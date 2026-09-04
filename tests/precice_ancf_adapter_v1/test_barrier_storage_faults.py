from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.precice_ancf_adapter_v1 import BarrierError, BridgeClock, RollingStore, ThreeSliceBarrier, canonical_tick, make_envelope


SLICES = ("slice_0000", "slice_0001", "slice_0002")


def ack(step=559, local=7, time_s=2.2075, sid="slice_0000", sequence=1, tx=None):
    return make_envelope(schema_version=1, run_id="stage285_run", case_id="stage285_case", slice_id=sid,
                         global_step=step, case_local_bridge_step=local, time_s=time_s,
                         integer_tick=canonical_tick(time_s), request_id=f"req-{step}-{sid}",
                         transaction_id=tx or f"tx-{step}-{sid}", sequence=sequence,
                         producer="fluid", consumer="structure", kind="force_ack",
                         payload={"force_N": [[1.0, 0.0]]}, ack="consumed")


class BarrierTests(unittest.TestCase):
    def setUp(self):
        self.barrier = ThreeSliceBarrier("stage285_run", "stage285_case", BridgeClock(559, 7, 2.2075))

    def test_three_slice_global_barrier_commits_only_after_all(self):
        self.assertFalse(self.barrier.submit(ack(sid=SLICES[0])))
        self.assertFalse(self.barrier.submit(ack(sid=SLICES[1])))
        self.assertTrue(self.barrier.submit(ack(sid=SLICES[2])))
        self.assertEqual([m.slice_id for m in self.barrier.commit()], list(SLICES))
        self.assertEqual(self.barrier.committed_steps, [559])

    def test_duplicate_stale_out_of_order_and_wrong_slice_fail_closed(self):
        self.barrier.submit(ack(sid=SLICES[0]))
        with self.assertRaises(BarrierError): self.barrier.submit(ack(sid=SLICES[0]))
        with self.assertRaises(BarrierError): self.barrier.submit(ack(step=561, local=9, time_s=2.2175, sid=SLICES[1]))
        with self.assertRaises(BarrierError): self.barrier.submit(ack(sid="slice_9999"))

    def test_tick_identity_ack_and_transport_faults(self):
        with self.assertRaises(BarrierError): self.barrier.submit(ack(time_s=2.207500001, sid=SLICES[0]))
        with self.assertRaises(BarrierError): self.barrier.submit(ack(sid=SLICES[0], sequence=2, tx="old"))
        for fault in ("timeout", "disconnect"):
            with self.assertRaises(BarrierError): self.barrier.fail_closed(fault)


class StorageTests(unittest.TestCase):
    def test_atomic_utf8_rolling_and_full_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RollingStore(Path(tmp))
            first = store.write_latest("restart", {"q": [1.0], "中文": "状态"}, step=559)
            second = store.write_latest("restart", {"q": [2.0]}, step=560)
            for step in range(3):
                store.append_journal({"step": step, "integer_tick": step * 5_000_000})
            self.assertEqual(json.loads(Path(second["path"]).read_text(encoding="utf-8"))["step"], 560)
            self.assertFalse(Path(first["path"]).with_name("step_559.json").exists())
            self.assertEqual(store.audit()["journal_records"], 3)
            self.assertTrue(store.audit()["latest_present"] is False)  # checkpoint/force not written yet

    def test_all_required_latest_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RollingStore(tmp)
            for category in ("checkpoint", "restart", "force"):
                item = store.write_latest(category, {"step": 559}, step=559)
                self.assertGreater(item["mtime_ns"], 0)
            audit = store.audit()
            self.assertTrue(audit["latest_present"])
            self.assertGreater(audit["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
