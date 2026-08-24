from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT, segment
from ..stage4f_d_e4_campaign_orchestration_repair_v1.gate import Contract, Gate, TERMINAL

RESULT = ROOT / "results/65_stage4f_d_e5_a_bounded_campaign_v1"
CASE = ROOT / "cases/openfoam/stage4f_d_e5_a_bounded_campaign_v1"
RUNTIME = ROOT / "runtime/stage4f_d_e5_a_bounded_campaign_v1"
SOURCE = ROOT / "cases/openfoam/stage4f_d_e4_bounded_campaign_v2_segment4/block_3/checkpoints/checkpoint_step00000479_cb25680360ce.json"
SOURCE_SHA = "3e100d2572bc9495cce1a5c3ba143a270f92b0139a5cb2cd1f4c0f5326ee8e4c"
RUN_ID = "stage65_e5_a_bounded_campaign_v1"
CASE_ID = "stage4f_lowre_v2_1_uniform_3slice"
DT = 0.00125
DT_TICK = 1_250_000
STABILIZER_CONTRACT_SHA = "cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualify_source() -> dict:
    payload = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    actual = sha256(SOURCE)
    qualified = (
        actual == SOURCE_SHA
        and payload.get("status") == "committed"
        and payload.get("step") == 479
        and payload.get("time_tick") == 2_107_500_000
        and abs(float(payload.get("time_s")) - 2.1075) < 1e-15
    )
    return {
        "path": str(SOURCE.resolve()),
        "checkpoint_id": payload.get("checkpoint_id"),
        "parent_checkpoint_id": payload.get("parent_checkpoint_id"),
        "step": payload.get("step"),
        "time_s": payload.get("time_s"),
        "tick": payload.get("time_tick"),
        "manifest_sha256": payload.get("slice_manifest_sha256"),
        "config_sha256": payload.get("config_sha256"),
        "sha256": actual,
        "qualified": qualified,
    }


def frozen_contract() -> Contract:
    return Contract(
        run_id=RUN_ID,
        source_checkpoint_path=str(SOURCE.resolve()),
        source_checkpoint_sha256=SOURCE_SHA,
        source_step=479,
        source_tick=2_107_500_000,
        source_time=2.1075,
        dt_global=DT,
        authorized_blocks=4,
        steps_per_block=10,
        authorized_steps=40,
        first_target_step=480,
        last_target_step=519,
        first_target_tick=2_108_750_000,
        last_target_tick=2_157_500_000,
        terminal_state=TERMINAL,
        no_auto_continuation=True,
        no_same_runtime_retry=True,
    )


def execution_contract() -> dict:
    c = frozen_contract()
    payload = json.loads(c.canonical())
    payload.update({
        "contract_sha256": c.sha256(),
        "case_id": CASE_ID,
        "source": qualify_source(),
        "no_cross_run_artifact_reuse": True,
        "next_segment_requires_new_authorization": True,
        "max_wall_clock_s": 14_400,
        "max_disk_bytes": 20 * 1024**3,
        "stabilizer_contract_sha256": STABILIZER_CONTRACT_SHA,
    })
    return payload


def run() -> dict:
    RESULT.mkdir(parents=True, exist_ok=True)
    if (RESULT / "E5_A_execution.json").exists() or any(RESULT.glob("block_*_execution.json")):
        raise RuntimeError("same runtime retry or existing execution evidence rejected")
    CASE.mkdir(parents=True, exist_ok=False)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if any(RUNTIME.glob("block_*")):
        raise RuntimeError("existing block runtime rejected")
    contract_payload = execution_contract()
    if not contract_payload["source"]["qualified"]:
        raise RuntimeError("source checkpoint qualification failed")
    atomic_write_json(RESULT / "execution_contract.json", contract_payload)
    gate = Gate(frozen_contract())
    source_before = sha256(SOURCE)
    parent = SOURCE
    blocks = []
    started = time.monotonic()
    for block_index in range(frozen_contract().authorized_blocks):
        gate.begin_block(block_index)
        first_step = 480 + block_index * 10
        start_time = 2.1075 + block_index * 10 * DT
        output = segment(
            f"E5_STAGE65_A_BLOCK_{block_index}", RUN_ID, DT, first_step, 10,
            start_time, CASE / f"block_{block_index}",
            RUNTIME / f"block_{block_index}", parent,
        )
        atomic_write_json(RESULT / f"block_{block_index}_execution.json", output)
        blocks.append(output)
        if output.get("physical_committed_steps") != 10 or output.get("fully_audited_steps") != 10:
            return {"status": "failed", "blocks": blocks, "source_sha_before": source_before,
                    "source_sha_after": sha256(SOURCE)}
        for step in range(first_step, first_step + 10):
            gate.commit_step(step)
        parent = Path(output["steps"][-1]["checkpoint"])
        if block_index < frozen_contract().authorized_blocks - 1:
            gate.next_block()
    if gate.state != TERMINAL:
        raise RuntimeError("authorized terminal state not reached")
    result = {
        "status": "completed", "terminal_state": gate.state,
        "attempted_next_block": False, "attempted_next_step": False,
        "blocks": blocks, "source_sha_before": source_before,
        "source_sha_after": sha256(SOURCE), "wall_clock_s": time.monotonic() - started,
        "disk_bytes": sum(p.stat().st_size for p in CASE.rglob("*") if p.is_file()),
    }
    atomic_write_json(RESULT / "E5_A_execution.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
