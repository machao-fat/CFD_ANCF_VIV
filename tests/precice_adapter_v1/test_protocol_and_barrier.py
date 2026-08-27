from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from coupling.precice_adapter_v1 import (
    BarrierError,
    FileTransport,
    GlobalBarrier,
    NoCfdViolation,
    ProtocolError,
    assert_no_processes_started,
    make_message,
    validate_probe_only_contract,
)


def message(*, slice_id: str = "slice_0000", global_step: int = 0,
            local_step: int = 0, time_s: float = 0.0, sequence: int = 1,
            kind: str = "force", payload: dict | None = None):
    return make_message(
        schema_version=1, run_id="offline_run269", case_id="offline_case269",
        slice_id=slice_id, global_step=global_step,
        case_local_bridge_step=local_step, time_s=time_s,
        integer_tick=int(round(time_s * 1e9)), request_id=f"req-{global_step}-{slice_id}",
        transaction_id=f"tx-{global_step}-{slice_id}", sequence=sequence,
        producer="mock-cfd", consumer="mock-ancf", kind=kind,
        payload=payload or {"force_N": [1.0, 2.0, 0.0]}, ack="consumed",
    )


class ProtocolTests(unittest.TestCase):
    def test_canonical_hash_and_utf8_roundtrip(self) -> None:
        msg = message(payload={"中文": "稳定", "force_N": [1.0, 2.0, 0.0]})
        encoded = msg.canonical_json()
        self.assertEqual(json.loads(encoded)["payload"]["中文"], "稳定")
        self.assertEqual(msg, type(msg)(**json.loads(encoded)))

    def test_hash_time_tick_identity_and_nonfinite_fail_closed(self) -> None:
        msg = message(time_s=0.00125, local_step=1)
        raw = json.loads(msg.canonical_json())
        raw["integer_tick"] += 1
        with self.assertRaises(ProtocolError):
            type(msg)(**raw).validate()
        raw = json.loads(msg.canonical_json())
        raw["payload"]["force_N"][0] = math.nan
        with self.assertRaises(ProtocolError):
            type(msg)(**raw).validate()

    def test_file_transport_is_atomic_contract_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transport = FileTransport(Path(tmp) / "messages.jsonl")
            transport.send(message())
            received = transport.receive_all()
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].payload_hash, message().payload_hash)


class BarrierTests(unittest.TestCase):
    def test_three_participant_barrier_requires_all_and_commits_once(self) -> None:
        barrier = GlobalBarrier(frozenset({"slice_0000", "slice_0001", "slice_0002"}))
        self.assertFalse(barrier.submit(message(slice_id="slice_0000")))
        self.assertFalse(barrier.submit(message(slice_id="slice_0001")))
        self.assertTrue(barrier.submit(message(slice_id="slice_0002")))
        committed = barrier.commit()
        self.assertEqual([m.slice_id for m in committed], ["slice_0000", "slice_0001", "slice_0002"])
        with self.assertRaises(BarrierError):
            barrier.commit()

    def test_duplicate_old_out_of_order_and_identity_mismatch_rejected(self) -> None:
        barrier = GlobalBarrier(frozenset({"slice_0000", "slice_0001"}))
        first = message(slice_id="slice_0000")
        barrier.submit(first)
        with self.assertRaises(BarrierError):
            barrier.submit(first)
        with self.assertRaises(BarrierError):
            barrier.submit(message(slice_id="slice_0000", global_step=2, local_step=2, time_s=0.002))
        with self.assertRaises(BarrierError):
            barrier.submit(message(slice_id="slice_0001", local_step=1, time_s=0.00125))

    def test_next_step_after_commit_and_stale_ack_rejected(self) -> None:
        barrier = GlobalBarrier(frozenset({"slice_0000", "slice_0001"}))
        for sid in ("slice_0000", "slice_0001"):
            barrier.submit(message(slice_id=sid))
        barrier.commit()
        with self.assertRaises(BarrierError):
            barrier.submit(message(slice_id="slice_0000"))
        barrier.submit(message(slice_id="slice_0000", global_step=1, local_step=1, time_s=0.00125))


class GuardTests(unittest.TestCase):
    def test_probe_only_requires_all_no_solver_guards(self) -> None:
        contract = {"no_cfd": True, "no_correction": True, "no_openfoam": True, "no_wsl": True}
        validate_probe_only_contract(contract)
        contract["no_wsl"] = False
        with self.assertRaises(NoCfdViolation):
            validate_probe_only_contract(contract)

    def test_any_mock_solver_launch_is_rejected(self) -> None:
        assert_no_processes_started({"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        with self.assertRaises(NoCfdViolation):
            assert_no_processes_started({"matlab": 0, "openfoam": 1, "wsl": 0, "cfd": 1})


if __name__ == "__main__":
    unittest.main()
