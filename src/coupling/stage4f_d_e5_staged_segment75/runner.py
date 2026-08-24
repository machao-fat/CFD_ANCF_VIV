from __future__ import annotations
import hashlib, json
from pathlib import Path
from ..stage4f_d_e5_b_bounded_campaign_v1 import runner as base

ROOT = base.ROOT
RESULT = ROOT / "results/75_stage4f_d_e5_candidate_1_attempt6"
CASE = ROOT / "cases/openfoam/stage75_e5_candidate_1_attempt6"
RUNTIME = ROOT / "runtime/stage75_e5_candidate_1_attempt6"
RUN_ID = "stage75_e5_candidate_1_attempt6"
SOURCE = ROOT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_*.json"

def _source_path():
    matches = list(SOURCE.parent.glob(SOURCE.name))
    if len(matches) != 1:
        raise RuntimeError(f"expected one Stage74 step559 checkpoint, found {len(matches)}")
    return matches[0]

def configure():
    source = _source_path()
    base.RESULT, base.CASE, base.RUNTIME, base.RUN_ID = RESULT, CASE, RUNTIME, RUN_ID
    base.SOURCE = source
    base.SOURCE_SHA = hashlib.sha256(source.read_bytes()).hexdigest()
    base.qualify_source = qualify_source
    base.frozen_contract = frozen_contract
    original_segment = base.segment
    from ..stage4f_three_slice_short_window_v1_repair2 import runner as low
    from ..multi_slice_driver import real_process
    from ..multi_slice_real_campaign import campaign
    original_bridge = real_process.materialize_legacy_motion_bridge
    def canonical_bridge(*, record, case, exchange_dir, seed=False, seed_time_s=None,
                         bridge_step_offset=1, seed_step_offset=None):
        # Global checkpoint steps remain absolute; the legacy reader bridge is
        # deliberately case-local (seed=0, first target=1).
        local = int(record["step"]) - 559
        mapped = dict(record)
        mapped["step"] = max(0, local - (0 if seed else 1))
        if seed:
            mapped["time_s"] = float(seed_time_s)
            return original_bridge(record=mapped, case=case, exchange_dir=exchange_dir,
                                   seed=True, seed_time_s=seed_time_s,
                                   bridge_step_offset=0, seed_step_offset=0)
        return original_bridge(record=mapped, case=case, exchange_dir=exchange_dir,
                               seed=False, bridge_step_offset=1)
    real_process.materialize_legacy_motion_bridge = canonical_bridge
    campaign.materialize_legacy_motion_bridge = canonical_bridge
    original_seed_records = low._seed_records
    def seed_records_target_time(manifest, adapter, state_runner, *, step, time_s):
        return original_seed_records(manifest, adapter, state_runner, step=step, time_s=time_s + 0.00125)
    low._seed_records = seed_records_target_time
    def segment_with_source_time(*args, **kwargs):
        # The legacy E5 wrapper passed the Stage65 start time unconditionally.
        # Stage75 starts from Stage74 step559 at 2.2075 s.
        if len(args) >= 6:
            args = list(args)
            block_index = int(args[0].rsplit("_", 1)[-1])
            args[5] = 2.2075 + block_index * 10 * 0.00125
            args = tuple(args)
        return original_segment(*args, **kwargs)
    base.segment = segment_with_source_time

def qualify_source():
    p = _source_path()
    x = json.loads(p.read_text(encoding="utf-8-sig"))
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"path": str(p.resolve()), "checkpoint_id": x.get("checkpoint_id"),
            "parent_checkpoint_id": x.get("parent_checkpoint_id"), "step": x.get("step"),
            "time_s": x.get("time_s"), "tick": x.get("time_tick"),
            "manifest_sha256": x.get("slice_manifest_sha256"), "config_sha256": x.get("config_sha256"),
            "sha256": actual, "qualified": actual == base.SOURCE_SHA and x.get("status") == "committed"
            and x.get("step") == 559 and x.get("time_tick") == 2207500000}

def frozen_contract():
    c = base.Contract(run_id=RUN_ID, source_checkpoint_path=str(_source_path().resolve()),
        source_checkpoint_sha256=base.SOURCE_SHA, source_step=559, source_tick=2207500000,
        source_time=2.2075, dt_global=0.00125, authorized_blocks=4, steps_per_block=10,
        authorized_steps=40, first_target_step=560, last_target_step=599,
        first_target_tick=2208750000, last_target_tick=2257500000,
        terminal_state=base.TERMINAL, no_auto_continuation=True, no_same_runtime_retry=True)
    return c

def run():
    configure()
    return base.run()

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
