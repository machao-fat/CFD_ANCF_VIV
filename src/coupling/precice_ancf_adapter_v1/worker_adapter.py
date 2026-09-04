from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .mapping import BridgeClock, MappingMatrix
from .protocol import Envelope, ProtocolError, make_envelope


@dataclass(frozen=True)
class WorkerRestartState:
    q: Sequence[Sequence[float]]
    qdot: Sequence[Sequence[float]]
    qddot: Sequence[Sequence[float]]

    def validate(self) -> None:
        if not self.q or len(self.q) != len(self.qdot) or len(self.q) != len(self.qddot):
            raise ProtocolError("invalid q/qdot/qddot restart state")
        width = len(self.q[0])
        if width == 0 or any(len(v) != width for group in (self.q, self.qdot, self.qddot) for v in group):
            raise ProtocolError("inconsistent restart vector dimensions")


@dataclass
class AncfPreciceSliceAdapter:
    """Adapter boundary: packages C++ state and validates a conservative force reply."""

    run_id: str
    case_id: str
    slice_id: str
    clock: BridgeClock
    mapping: MappingMatrix
    producer: str = "ancf-cpp-worker"
    consumer: str = "precice-fluid"

    def displacement_request(self, global_step: int, state: WorkerRestartState) -> Envelope:
        state.validate()
        gs, local, time_s, tick = self.clock.identity(global_step)
        values = self.mapping.consistent_displacement(state.q)
        return make_envelope(schema_version=1, run_id=self.run_id, case_id=self.case_id, slice_id=self.slice_id,
                             global_step=gs, case_local_bridge_step=local, time_s=time_s, integer_tick=tick,
                             request_id=f"{self.run_id}:{self.slice_id}:request:{gs}",
                             transaction_id=f"{self.run_id}:{self.slice_id}:transaction:{gs}",
                             sequence=gs - self.clock.global_origin + 1, producer=self.producer,
                             consumer=self.consumer, kind="displacement", payload={"displacement_m": values,
                             "q": state.q, "qdot": state.qdot, "qddot": state.qddot}, ack="produced")

    def consume_force(self, request: Envelope, force_reply: Envelope) -> list[list[float]]:
        request.validate()
        force_reply.validate({"run_id": request.run_id, "case_id": request.case_id, "slice_id": request.slice_id,
                              "global_step": request.global_step, "case_local_bridge_step": request.case_local_bridge_step,
                              "time_s": request.time_s, "integer_tick": request.integer_tick,
                              "request_id": request.request_id, "transaction_id": request.transaction_id,
                              "sequence": request.sequence})
        if force_reply.kind != "force" or force_reply.ack != "produced":
            raise ProtocolError("force reply must be produced force")
        raw = force_reply.payload.get("force_N")
        if not isinstance(raw, list):
            raise ProtocolError("force reply lacks force_N")
        return self.mapping.conservative_force(raw)

    def consumed_ack(self, force_reply: Envelope) -> Envelope:
        force_reply.validate()
        return make_envelope(schema_version=1, run_id=force_reply.run_id, case_id=force_reply.case_id,
                             slice_id=force_reply.slice_id, global_step=force_reply.global_step,
                             case_local_bridge_step=force_reply.case_local_bridge_step, time_s=force_reply.time_s,
                             integer_tick=force_reply.integer_tick, request_id=force_reply.request_id,
                             transaction_id=force_reply.transaction_id, sequence=force_reply.sequence,
                             producer="ancf-cpp-worker", consumer="precice-fluid", kind="force_ack",
                             payload={"force_payload_hash": force_reply.payload_hash}, ack="consumed")
