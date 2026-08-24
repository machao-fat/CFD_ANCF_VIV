import unittest

from src.coupling.performance_optimization_v1.contracts import IPCMessage, SCHEMA_VERSION
from src.coupling.performance_optimization_v1.ipc import IPCProtocolError, PersistentIPC


def message(channel, sequence=1, request="q", transaction="t", **kwargs):
    return IPCMessage.create(run_id=channel.run_id, case_id=channel.case_id, slice_id=channel.slice_id,
                             global_step=kwargs.pop("global_step", sequence - 1),
                             case_local_bridge_step=sequence - 1, time_s=(sequence - 1) * 0.0025,
                             integer_tick=sequence - 1, request_id=request, transaction_id=transaction,
                             sequence=sequence, producer="matlab", consumer=f"openfoam_{channel.slice_id}", ack=False, payload={})


class IPCTests(unittest.TestCase):
    def test_stale_duplicate_and_out_of_order_fail_closed(self):
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        channel.send(message(channel))
        with self.assertRaises(IPCProtocolError):
            channel.send(message(channel, sequence=1, request="q2", transaction="t2"))
        self.assertTrue(channel.poisoned)

        for bad_sequence in (2, 3):
            fresh = PersistentIPC(run_id="r", case_id="c", slice_id=0)
            with self.assertRaises(IPCProtocolError):
                fresh.send(message(fresh, sequence=bad_sequence, request="q", transaction="t"))

    def test_identity_disconnect_and_timeout_fail_closed(self):
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0, timeout_s=0.001)
        bad = IPCMessage.create(run_id="other", case_id="c", slice_id=0, global_step=0, case_local_bridge_step=0,
                               time_s=0.0, integer_tick=0, request_id="q", transaction_id="t", sequence=1,
                               producer="p", consumer="c", ack=True, payload={})
        with self.assertRaises(IPCProtocolError):
            channel.send(bad)
        disconnected = PersistentIPC(run_id="r", case_id="c", slice_id=0, timeout_s=0.001)
        disconnected.disconnect()
        with self.assertRaises(IPCProtocolError):
            disconnected.receive()
        timeout = PersistentIPC(run_id="r", case_id="c", slice_id=0, timeout_s=0.001)
        with self.assertRaises(IPCProtocolError):
            timeout.receive()

    def test_stale_step_tick_time_rejected_even_with_new_sequence(self):
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        channel.send(message(channel, sequence=1))
        stale = message(channel, sequence=2, request="q2", transaction="t2", global_step=0)
        with self.assertRaises(IPCProtocolError):
            channel.send(stale)

    def test_schema_and_payload_hash_fail_closed(self):
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        bad_schema = IPCMessage.create(run_id="r", case_id="c", slice_id=0,
                                       global_step=0, case_local_bridge_step=0, time_s=0.0,
                                       integer_tick=0, request_id="q", transaction_id="t",
                                       sequence=1, producer="p", consumer="c", ack=False,
                                       payload={"x": 1})
        object.__setattr__(bad_schema, "schema_version", "wrong")
        with self.assertRaises(IPCProtocolError):
            channel.send(bad_schema)

        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        bad_hash = IPCMessage.create(run_id="r", case_id="c", slice_id=0,
                                     global_step=0, case_local_bridge_step=0, time_s=0.0,
                                     integer_tick=0, request_id="q", transaction_id="t",
                                     sequence=1, producer="p", consumer="c", ack=False,
                                     payload={"x": 1})
        object.__setattr__(bad_hash, "payload_hash", "0" * 64)
        with self.assertRaises(IPCProtocolError):
            channel.send(bad_hash)

    def test_endpoint_identity_and_ack_of_ack_fail_closed(self):
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        bad = IPCMessage.create(run_id="r", case_id="c", slice_id=0,
                                global_step=0, case_local_bridge_step=0, time_s=0.0,
                                integer_tick=0, request_id="q", transaction_id="t",
                                sequence=1, producer="unknown", consumer="openfoam_0",
                                ack=False, payload={})
        with self.assertRaises(IPCProtocolError):
            channel.send(bad)
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        request = IPCMessage.create(run_id="r", case_id="c", slice_id=0,
                                    global_step=0, case_local_bridge_step=0, time_s=0.0,
                                    integer_tick=0, request_id="q", transaction_id="t",
                                    sequence=1, producer="matlab", consumer="openfoam_0",
                                    ack=False, payload={})
        ack = channel.ack(request, producer="openfoam_0", consumer="matlab", sequence=1)
        with self.assertRaises(IPCProtocolError):
            channel.ack(ack, producer="matlab", consumer="openfoam_0", sequence=2)

    def test_ack_payload_and_bridge_step_are_checked(self):
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        request = IPCMessage.create(run_id="r", case_id="c", slice_id=0,
                                    global_step=0, case_local_bridge_step=0, time_s=0.0,
                                    integer_tick=0, request_id="q", transaction_id="t",
                                    sequence=1, producer="matlab", consumer="openfoam_0",
                                    ack=False, payload={"motion": 0})
        channel.send(request)
        bad_ack = IPCMessage.create(run_id="r", case_id="c", slice_id=0,
                                    global_step=0, case_local_bridge_step=0, time_s=0.0,
                                    integer_tick=0, request_id="q", transaction_id="t",
                                    sequence=1, producer="openfoam_0", consumer="matlab",
                                    ack=True, payload={"ack_for": "wrong"})
        with self.assertRaises(IPCProtocolError):
            channel.send(bad_ack)
        channel = PersistentIPC(run_id="r", case_id="c", slice_id=0)
        stale_bridge = IPCMessage.create(run_id="r", case_id="c", slice_id=0,
                                         global_step=1, case_local_bridge_step=0, time_s=0.0025,
                                         integer_tick=1, request_id="q2", transaction_id="t2",
                                         sequence=2, producer="matlab", consumer="openfoam_0",
                                         ack=False, payload={})
        channel.send(request)
        with self.assertRaises(IPCProtocolError):
            channel.send(stale_bridge)
