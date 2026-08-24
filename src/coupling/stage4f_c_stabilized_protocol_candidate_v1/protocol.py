from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

ALPHA = 0.1
CD_LIMIT = 10.0
VELOCITY_LIMIT = 0.01
CFL_LIMIT = 0.8

class State(str, Enum):
    COMMITTED="COMMITTED"; RAW_LOADS_AUDITED="RAW_LOADS_AUDITED"; REJECTED="REJECTED"; APPLIED_LOADS_PREPARED="APPLIED_LOADS_PREPARED"; CHECKPOINT_PREPARED="CHECKPOINT_PREPARED"

@dataclass(frozen=True)
class CandidateTransaction:
    step: int
    raw_force: tuple[float, ...]
    previous_applied_force: tuple[float, ...]
    state: State = State.COMMITTED

    def audit(self, *, max_cd: float, velocity_error: float, max_cfl: float) -> "CandidateTransaction":
        values=(max_cd, velocity_error, max_cfl, *self.raw_force, *self.previous_applied_force)
        if any(not math.isfinite(float(v)) for v in values): raise ValueError("non-finite transaction")
        if max_cfl >= CFL_LIMIT or abs(max_cd) > CD_LIMIT or abs(velocity_error) > VELOCITY_LIMIT:
            return CandidateTransaction(self.step, self.raw_force, self.previous_applied_force, State.REJECTED)
        return CandidateTransaction(self.step, self.raw_force, self.previous_applied_force, State.RAW_LOADS_AUDITED)

    def prepare_applied(self) -> tuple["CandidateTransaction", tuple[float, ...]]:
        if self.state != State.RAW_LOADS_AUDITED: raise ValueError("only audited raw loads may be relaxed")
        if len(self.raw_force) != len(self.previous_applied_force): raise ValueError("force shape mismatch")
        applied=tuple((1-ALPHA)*old+ALPHA*raw for raw,old in zip(self.raw_force,self.previous_applied_force))
        return CandidateTransaction(self.step,self.raw_force,self.previous_applied_force,State.APPLIED_LOADS_PREPARED), applied

    def prepare_checkpoint(self) -> "CandidateTransaction":
        if self.state != State.APPLIED_LOADS_PREPARED: raise ValueError("checkpoint requires applied loads")
        return CandidateTransaction(self.step,self.raw_force,self.previous_applied_force,State.CHECKPOINT_PREPARED)

    def rollback_target(self, last_committed: str) -> str:
        if self.state != State.REJECTED or not last_committed: raise ValueError("rollback requires rejected transaction and committed target")
        return last_committed
