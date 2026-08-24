from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..stage4f_d_e5_b_bounded_campaign_v1 import runner as base

ROOT = base.ROOT
RESULT = ROOT / "results/80_stage75_e5_candidate_1_attempt7"
CASE = ROOT / "cases/openfoam/stage75_e5_candidate_1_attempt7"
RUNTIME = ROOT / "runtime/stage75_e5_candidate_1_attempt7"
RUN_ID = "stage75_e5_candidate_1_attempt7"
SOURCE = ROOT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"


def _source_path() -> Path:
    if not SOURCE.is_file():
        raise RuntimeError("Stage74 step559 source checkpoint is missing")
    return SOURCE


def qualify_source():
    path = _source_path()
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path.resolve()), "checkpoint_id": value.get("checkpoint_id"),
        "parent_checkpoint_id": value.get("parent_checkpoint_id"),
        "step": value.get("step"), "time_s": value.get("time_s"),
        "tick": value.get("time_tick"), "sha256": digest,
        "qualified": value.get("status") == "committed" and value.get("step") == 559
        and value.get("time_tick") == 2207500000,
    }


def frozen_contract():
    return base.Contract(
        run_id=RUN_ID, source_checkpoint_path=str(_source_path().resolve()),
        source_checkpoint_sha256=hashlib.sha256(_source_path().read_bytes()).hexdigest(),
        source_step=559, source_tick=2207500000, source_time=2.2075,
        dt_global=0.00125, authorized_blocks=4, steps_per_block=10,
        authorized_steps=40, first_target_step=560, last_target_step=599,
        first_target_tick=2208750000, last_target_tick=2257500000,
        terminal_state=base.TERMINAL, no_auto_continuation=True,
        no_same_runtime_retry=True,
    )


def configure():
    source = _source_path()
    base.RESULT, base.CASE, base.RUNTIME, base.RUN_ID = RESULT, CASE, RUNTIME, RUN_ID
    base.SOURCE = source
    base.SOURCE_SHA = hashlib.sha256(source.read_bytes()).hexdigest()
    base.qualify_source = qualify_source
    base.frozen_contract = frozen_contract
    original_segment = base.segment

    def segment_with_source_time(*args, **kwargs):
        args = list(args)
        if len(args) >= 6:
            block_index = int(str(args[0]).rsplit("_", 1)[-1])
            args[5] = 2.2075 + block_index * 10 * 0.00125
        return original_segment(*args, **kwargs)

    base.segment = segment_with_source_time


def run():
    configure()
    return base.run()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
