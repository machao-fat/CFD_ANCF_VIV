from __future__ import annotations

import unittest

from coupling.performance_optimization_v1.contracts import IPCMessage
from coupling.performance_optimization_v2.ipc import MappedIPCConfig, MappedIPCError, MappedPersistentIPC


class IPCTests(unittest.TestCase):
    def channel(self):
        return MappedPersistentIPC(MappedIPCConfig("run95", "case95", 0, 559, 2.2075, 2207500000, .00125), timeout_s=.1)

    def message(self, *, step=560, bridge=1, tick=2208750000, sequence=1):
        return IPCMessage.create(run_id="run95", case_id="case95", slice_id=0, global_step=step,
            case_local_bridge_step=bridge, time_s=2.20875, integer_tick=tick, request_id=f"r{sequence}",
            transaction_id=f"t{sequence}", sequence=sequence, producer="matlab", consumer="openfoam_0", ack=False,
            payload={"motion": step})

    def test_mapping_and_ack(self):
        channel = self.channel(); request = self.message(); channel.send(request); received = channel.receive(); self.assertEqual(received.case_local_bridge_step, 1)
        ack = channel.ack(received, producer="openfoam_0", consumer="matlab", sequence=1); channel.send(ack); self.assertTrue(channel.receive().ack)

    def test_wrong_bridge_and_tick_fail_closed(self):
        with self.assertRaises(MappedIPCError): self.channel().send(self.message(bridge=560))
        with self.assertRaises(MappedIPCError): self.channel().send(self.message(tick=2208750001))

    def test_disconnect_is_fail_closed(self):
        channel = self.channel(); channel.disconnect()
        with self.assertRaises(Exception): channel.send(self.message())


if __name__ == "__main__": unittest.main()
