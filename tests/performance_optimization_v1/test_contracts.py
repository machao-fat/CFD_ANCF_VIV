import math
import unittest

from src.coupling.performance_optimization_v1.contracts import (
    IPCMessage, OptimizationConfig, ProtocolViolation, WorkerEnvelope,
)


class ContractTests(unittest.TestCase):
    def test_config_is_immutable_scope(self):
        config = OptimizationConfig()
        config.validate()
        self.assertEqual(config.steps_per_segment, 20)
        with self.assertRaises(ProtocolViolation):
            OptimizationConfig(slice_count=5).validate()

    def test_finite_and_worker_identity(self):
        with self.assertRaises(ProtocolViolation):
            WorkerEnvelope.build(run_id="r", case_id="c", global_step=0, case_local_bridge_step=0,
                                 time_s=0.0, integer_tick=0, payload={"x": math.nan}, worker_pid=1)
        envelope = WorkerEnvelope.build(run_id="r", case_id="c", global_step=2, case_local_bridge_step=2,
                                        time_s=0.005, integer_tick=2, payload={"x": 1.0}, worker_pid=1)
        envelope.validate_against(run_id="r", case_id="c", global_step=2, case_local_bridge_step=2,
                                  time_s=0.005, integer_tick=2)
        with self.assertRaises(ProtocolViolation):
            envelope.validate_against(run_id="r", case_id="c", global_step=3, case_local_bridge_step=3,
                                      time_s=0.0075, integer_tick=3)

    def test_ipc_message_has_required_identity(self):
        message = IPCMessage.create(run_id="r", case_id="c", slice_id=0, global_step=0,
                                    case_local_bridge_step=0, time_s=0.0, integer_tick=0,
                                    request_id="q", transaction_id="t", sequence=1,
                                    producer="a", consumer="b", ack=True, payload={"motion": 0})
        self.assertEqual(message.schema_version, "performance_optimization_v1.0")
        self.assertEqual(len(message.payload_hash), 64)

    def test_metadata_nan_and_negative_step_are_rejected(self):
        with self.assertRaises(ProtocolViolation):
            WorkerEnvelope.build(run_id="r", case_id="c", global_step=0, case_local_bridge_step=0,
                                 time_s=float("nan"), integer_tick=0, payload={}, worker_pid=1)
        with self.assertRaises(ProtocolViolation):
            IPCMessage.create(run_id="r", case_id="c", slice_id=0, global_step=-1,
                               case_local_bridge_step=0, time_s=0.0, integer_tick=0,
                               request_id="q", transaction_id="t", sequence=1,
                               producer="a", consumer="b", ack=False, payload={})
