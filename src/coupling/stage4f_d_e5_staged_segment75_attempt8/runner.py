from __future__ import annotations
import hashlib, json
from pathlib import Path
from ..stage4f_d_e5_b_bounded_campaign_v1 import runner as base

ROOT = base.ROOT
RESULT = ROOT / "results/81_stage75_e5_candidate_1_attempt8"
CASE = ROOT / "cases/openfoam/stage75_e5_candidate_1_attempt8"
RUNTIME = ROOT / "runtime/stage75_e5_candidate_1_attempt8"
RUN_ID = "stage75_e5_candidate_1_attempt8"
SOURCE = ROOT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"

def _source_path():
    if not SOURCE.is_file(): raise RuntimeError("accepted source checkpoint missing")
    return SOURCE

def qualify_source():
    p = _source_path(); x = json.loads(p.read_text(encoding="utf-8-sig"))
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"path": str(p.resolve()), "checkpoint_id": x.get("checkpoint_id"),
            "parent_checkpoint_id": x.get("parent_checkpoint_id"), "step": x.get("step"),
            "time_s": x.get("time_s"), "tick": x.get("time_tick"), "sha256": digest,
            "qualified": x.get("status") == "committed" and x.get("step") == 559
            and x.get("time_tick") == 2207500000}

def frozen_contract():
    return base.Contract(run_id=RUN_ID, source_checkpoint_path=str(_source_path().resolve()),
        source_checkpoint_sha256=hashlib.sha256(_source_path().read_bytes()).hexdigest(),
        source_step=559, source_tick=2207500000, source_time=2.2075,
        dt_global=.00125, authorized_blocks=4, steps_per_block=10,
        authorized_steps=40, first_target_step=560, last_target_step=599,
        first_target_tick=2208750000, last_target_tick=2257500000,
        terminal_state=base.TERMINAL, no_auto_continuation=True, no_same_runtime_retry=True)

def configure():
    base.RESULT, base.CASE, base.RUNTIME, base.RUN_ID = RESULT, CASE, RUNTIME, RUN_ID
    base.SOURCE = _source_path(); base.SOURCE_SHA = hashlib.sha256(base.SOURCE.read_bytes()).hexdigest()
    base.qualify_source = qualify_source; base.frozen_contract = frozen_contract
    original = base.segment
    def segment_with_source_time(*args, **kwargs):
        values = list(args)
        if len(values) >= 6:
            block = int(str(values[0]).rsplit("_", 1)[-1]); values[5] = 2.2075 + block * 10 * .00125
        return original(*values, **kwargs)
    base.segment = segment_with_source_time

def run():
    configure(); return base.run()

if __name__ == "__main__": print(json.dumps(run(), ensure_ascii=False))
