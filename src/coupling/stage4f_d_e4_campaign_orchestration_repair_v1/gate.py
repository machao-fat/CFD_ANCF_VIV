import hashlib, json
from dataclasses import dataclass

TERMINAL = "AUTHORIZED_WINDOW_COMPLETE"

@dataclass(frozen=True)
class Contract:
    run_id: str
    source_checkpoint_path: str
    source_checkpoint_sha256: str
    source_step: int = 319
    source_tick: int = 1907500000
    source_time: float = 1.9075
    dt_global: float = .00125
    authorized_blocks: int = 4
    steps_per_block: int = 10
    authorized_steps: int = 40
    first_target_step: int = 320
    last_target_step: int = 359
    first_target_tick: int = 1908750000
    last_target_tick: int = 1957500000
    terminal_state: str = TERMINAL
    no_auto_continuation: bool = True
    no_same_runtime_retry: bool = True

    def validate(self):
        if self.authorized_steps != self.authorized_blocks * self.steps_per_block: raise ValueError("step/block mismatch")
        if self.last_target_step - self.first_target_step + 1 != self.authorized_steps: raise ValueError("target range mismatch")
        if self.first_target_step != self.source_step + 1: raise ValueError("source/target step mismatch")
        if self.first_target_tick != self.source_tick + 1_250_000: raise ValueError("first tick mismatch")
        if self.last_target_tick != self.first_target_tick + (self.authorized_steps-1)*1_250_000: raise ValueError("last tick mismatch")
        if self.terminal_state != TERMINAL: raise ValueError("terminal state mismatch")
        return True

    def canonical(self):
        self.validate(); return json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    def sha256(self): return hashlib.sha256(self.canonical().encode()).hexdigest()

class Gate:
    def __init__(self, contract):
        contract.validate(); self.c=contract; self.next_step=contract.first_target_step; self.block=0; self.state="RUNNING"; self.created=[]
    def begin_block(self, block):
        if self.state == TERMINAL: raise RuntimeError("window complete")
        if block != self.block or block >= self.c.authorized_blocks: raise RuntimeError("block out of authorized range")
    def commit_step(self, step):
        if self.state == TERMINAL: raise RuntimeError("window complete")
        if step != self.next_step or step > self.c.last_target_step: raise RuntimeError("step out of authorized range")
        self.created.append(step); self.next_step += 1
        if step == self.c.last_target_step: self.state=TERMINAL
    def next_block(self):
        if self.state == TERMINAL: raise RuntimeError("no next block after terminal")
        self.block += 1
        if self.block >= self.c.authorized_blocks: raise RuntimeError("block out of authorized range")
