from __future__ import annotations
import json
from pathlib import Path
from hashlib import sha256

ROOT = Path(__file__).resolve().parents[3]
RESULT = ROOT / "results/73_stage4f_d_e5_b_attempt2_closeout_v1"
SOURCE = ROOT / "results/72_stage4f_d_e5_b_bounded_campaign_attempt2"
CASE = ROOT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt2"

def dump(name, obj):
    p = RESULT / name
    p.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

def run():
    RESULT.mkdir(parents=True, exist_ok=True)
    blocks=[]; steps=[]; failures=[]
    for i in range(4):
        p=SOURCE/f"block_{i}_execution.json"
        if p.exists():
            j=json.loads(p.read_text(encoding="utf-8")); blocks.append(i)
            for s in j.get("steps", []): steps.append(s.get("step"))
            if j.get("status") != "completed": failures.append({"block":i,"status":j.get("status")})
    steps=sorted(x for x in steps if isinstance(x,int))
    cps=list(CASE.rglob("checkpoint_*.json"))
    registries=list(CASE.rglob("owned_process_registry.json"))
    proc=[]
    for p in registries:
        try: proc.extend(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e: failures.append({"registry":str(p),"error":str(e)})
    residual=sum(1 for x in proc if x.get("return_code") is None or x.get("cleanup_result") not in (None,"clean","natural_exit"))
    audit={"stage":"73","source_stage":"72","run_id":"stage72_e5_b_bounded_campaign_attempt2","blocks_present":blocks,"completed_blocks":len(blocks),"committed_steps":len(steps),"step_min":min(steps) if steps else None,"step_max":max(steps) if steps else None,"checkpoints":len(cps),"raw_snapshot_estimate":len(steps)*3,"owned_process_records":len(proc),"owned_residual":residual,"first_missing_step":550 if steps and max(steps)==549 else None,"partial_runtime_excluded":True,"gate":"do_not_pass","reason":"attempt stopped after block 2; block 3 and final window evidence absent"}
    dump("attempt2_partial_audit.json",audit)
    dump("closeout_gate.json",{"gate":"STAGE4F_D_E5_B_ATTEMPT2_CLOSEOUT_V1_GATE: do_not_pass","state":"FAILED_TERMINAL","audit":audit,"no_process_started":True,"source_read_only":True})
    return audit

if __name__ == "__main__": print(json.dumps(run(), ensure_ascii=False))
