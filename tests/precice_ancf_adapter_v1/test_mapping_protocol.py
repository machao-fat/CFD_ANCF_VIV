from __future__ import annotations

import json
import math
import unittest

from coupling.precice_ancf_adapter_v1 import AncfPreciceSliceAdapter, BridgeClock, MappingError, MappingMatrix, ProtocolError, WorkerRestartState, canonical_tick, make_envelope


def envelope(*, step=559, local=7, time_s=2.2075, slice_id="slice_0000", kind="force_ack", ack="consumed", sequence=1):
    return make_envelope(schema_version=1, run_id="stage285_run", case_id="stage285_case", slice_id=slice_id,
                         global_step=step, case_local_bridge_step=local, time_s=time_s,
                         integer_tick=canonical_tick(time_s), request_id=f"req-{step}-{slice_id}",
                         transaction_id=f"tx-{step}-{slice_id}", sequence=sequence, producer="precice-fluid",
                         consumer="ancf-structure", kind=kind, payload={"force_N": [[1.0, 0.0]]}, ack=ack)


class ClockTests(unittest.TestCase):
    def test_source_559_target_560_are_explicitly_mapped(self):
        clock = BridgeClock(559, 7, 2.2075)
        self.assertEqual(clock.identity(559), (559, 7, 2.2075, 2207500000))
        self.assertEqual(clock.identity(560), (560, 8, 2.2125, 2212500000))
        self.assertNotEqual(clock.local_step(560), 560)

    def test_wrong_dt_and_negative_origin_fail_closed(self):
        with self.assertRaises(MappingError):
            BridgeClock(0, 0, 0.0, 0.00125)
        with self.assertRaises(MappingError):
            BridgeClock(-1, 0, 0.0)


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.h = MappingMatrix(((1.0, 0.0), (0.5, 0.5), (0.0, 1.0)))

    def test_consistent_displacement_and_conservative_force(self):
        displacement = [[2.0, 0.0], [4.0, 0.0]]
        force = [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]
        self.assertEqual(self.h.consistent_displacement(displacement), [[2.0, 0.0], [3.0, 0.0], [4.0, 0.0]])
        self.assertEqual(self.h.conservative_force(force), [[2.0, 0.0], [4.0, 0.0]])

    def test_virtual_work_is_preserved(self):
        lhs, rhs = self.h.virtual_work([[2.0, 1.0], [4.0, -1.0]], [[1.0, 2.0], [2.0, 0.0], [3.0, -1.0]])
        self.assertAlmostEqual(lhs, rhs)

    def test_invalid_row_or_size_rejected(self):
        with self.assertRaises(MappingError):
            MappingMatrix(((0.4, 0.4),))
        with self.assertRaises(MappingError):
            self.h.consistent_displacement([[1.0, 2.0]])


class ProtocolTests(unittest.TestCase):
    def test_utf8_canonical_hash_roundtrip(self):
        msg = envelope()
        raw = msg.canonical_json()
        self.assertEqual(json.loads(raw)["payload_hash"], msg.payload_hash)
        self.assertEqual(msg, type(msg)(**json.loads(raw)))

    def test_tick_hash_nan_identity_faults(self):
        msg = envelope()
        raw = json.loads(msg.canonical_json())
        raw["integer_tick"] += 1
        with self.assertRaises(ProtocolError): type(msg)(**raw).validate()
        raw = json.loads(msg.canonical_json())
        raw["payload"]["force_N"][0][0] = math.nan
        with self.assertRaises(ProtocolError): type(msg)(**raw).validate()
        raw = json.loads(msg.canonical_json())
        raw["global_step"] = 560
        with self.assertRaises(ProtocolError): type(msg)(**raw).validate()

    def test_cpp_state_is_mapped_and_conservative_force_is_consumed(self):
        adapter = AncfPreciceSliceAdapter("stage285_run", "stage285_case", "slice_0000", BridgeClock(559, 7, 2.2075), MappingMatrix(((1.0, 0.0), (0.0, 1.0))))
        state = WorkerRestartState([[1.0, 0.0], [2.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]])
        request = adapter.displacement_request(559, state)
        self.assertEqual(request.payload["displacement_m"], [[1.0, 0.0], [2.0, 0.0]])
        force = make_envelope(schema_version=1, run_id=request.run_id, case_id=request.case_id, slice_id=request.slice_id, global_step=request.global_step, case_local_bridge_step=request.case_local_bridge_step, time_s=request.time_s, integer_tick=request.integer_tick, request_id=request.request_id, transaction_id=request.transaction_id, sequence=request.sequence, producer="precice-fluid", consumer="ancf-cpp-worker", kind="force", payload={"force_N": [[3.0, 0.0], [4.0, 0.0]]}, ack="produced")
        self.assertEqual(adapter.consume_force(request, force), [[3.0, 0.0], [4.0, 0.0]])
        self.assertEqual(adapter.consumed_ack(force).ack, "consumed")


if __name__ == "__main__":
    unittest.main()
