"""0.3.0 candidate 的纯内存伪 case adapter。"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Sequence
from .protocol import CandidateTransaction, State

@dataclass
class FakeAdapter:
    case_id: str
    run_id: str
    slice_ids: tuple[int, ...] = (0, 1, 2)
    consumed: set[tuple[str, str, int, int, int]] = field(default_factory=set)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, *, step: int, time_tick: int, raw_force: Sequence[float], previous_applied: Sequence[float], max_cd: float, velocity_error: float, max_cfl: float) -> dict[str, Any]:
        if step < 0 or time_tick < 0 or len(raw_force) != len(self.slice_ids): raise ValueError("invalid transaction identity")
        keys=[(self.case_id,self.run_id,step,time_tick,sid) for sid in self.slice_ids]
        if any(key in self.consumed for key in keys): raise ValueError("duplicate consumption")
        tx=CandidateTransaction(step,tuple(map(float,raw_force)),tuple(map(float,previous_applied))).audit(max_cd=max_cd,velocity_error=velocity_error,max_cfl=max_cfl)
        evidence={"case_id":self.case_id,"run_id":self.run_id,"step":step,"time_tick":time_tick,"slice_ids":list(self.slice_ids),"raw_force":list(tx.raw_force),"state":tx.state.value}
        if tx.state == State.REJECTED:
            evidence.update(committed=False,checkpoint_count=len(self.checkpoints),rollback=self.checkpoints[-1]["checkpoint_id"] if self.checkpoints else None)
            return evidence
        prepared,applied=tx.prepare_applied(); prepared=prepared.prepare_checkpoint()
        body=dict(evidence,state=prepared.state.value,applied_force=list(applied),parent_checkpoint=self.checkpoints[-1]["checkpoint_id"] if self.checkpoints else None)
        checkpoint_id=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:12]
        checkpoint=dict(body,state=State.COMMITTED.value,checkpoint_id=checkpoint_id,committed=True)
        self.checkpoints.append(checkpoint); self.consumed.update(keys)
        return checkpoint

    def restart(self, checkpoint_id: str) -> dict[str, Any]:
        matches=[row for row in self.checkpoints if row["checkpoint_id"]==checkpoint_id and row["committed"]]
        if len(matches)!=1: raise ValueError("restart target is not one committed checkpoint")
        return dict(matches[0])
