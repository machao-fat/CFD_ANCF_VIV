from __future__ import annotations

import unittest

from coupling.precice_adapter_v1 import (
    ParticipantError,
    ParticipantSession,
    ParticipantState,
    make_message,
)


class Backend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.payload = {"force_N": [0.1, 0.2, 0.0]}

    def initialize(self) -> None: self.calls.append("initialize")
    def write_displacement(self, payload) -> None: self.calls.append("write")
    def advance(self, dt_s) -> None: self.calls.append("advance")
    def read_force(self): self.calls.append("read"); return self.payload
    def finalize(self) -> None: self.calls.append("finalize")


def msg(kind: str, step: int = 0, local: int = 0, time_s: float = 0.0):
    return make_message(
        schema_version=1, run_id="run270", case_id="case270", slice_id="slice_0000",
        global_step=step, case_local_bridge_step=local, time_s=time_s,
        integer_tick=int(round(time_s * 1e9)), request_id=f"req-{kind}-{step}",
        transaction_id=f"tx-{kind}-{step}", sequence=step + 1,
        producer="ancf", consumer="precice", kind=kind,
        payload={"displacement_m": [0.0, 0.0, 0.0]}, ack="consumed",
    )


class ParticipantLifecycleTests(unittest.TestCase):
    def test_strict_initialize_write_advance_read_finalize(self) -> None:
        backend = Backend()
        session = ParticipantSession(backend, "run270", "case270", "slice_0000", 0.00125)
        session.initialize()
        session.write_displacement(msg("displacement"))
        session.advance()
        self.assertEqual(session.read_force(msg("force")), backend.payload)
        session.finalize()
        self.assertEqual(session.state, ParticipantState.FINALIZED)
        self.assertEqual(backend.calls, ["initialize", "write", "advance", "read", "finalize"])

    def test_duplicate_write_wrong_step_and_incomplete_finalize_fail_closed(self) -> None:
        session = ParticipantSession(Backend(), "run270", "case270", "slice_0000", 0.00125)
        session.initialize()
        session.write_displacement(msg("displacement"))
        with self.assertRaises(ParticipantError):
            session.write_displacement(msg("displacement"))
        with self.assertRaises(ParticipantError):
            session.finalize()

    def test_identity_time_and_kind_mismatch_rejected(self) -> None:
        session = ParticipantSession(Backend(), "run270", "case270", "slice_0000", 0.00125)
        session.initialize()
        with self.assertRaises(ParticipantError):
            session.write_displacement(msg("force"))
        self.assertEqual(session.state, ParticipantState.FAILED)
        with self.assertRaises(ParticipantError):
            session.write_displacement(make_message(
                schema_version=1, run_id="other", case_id="case270", slice_id="slice_0000",
                global_step=0, case_local_bridge_step=0, time_s=0.0, integer_tick=0,
                request_id="req", transaction_id="tx", sequence=1, producer="ancf",
                consumer="precice", kind="displacement", payload={"x": 0}, ack="consumed"))


if __name__ == "__main__":
    unittest.main()
