from __future__ import annotations
import json,os
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_c_stabilized_production_hook_v1.run_restart_probe import build,ROOT

RESULT=ROOT/'results/18_stage4f_c_stabilized_restart_lineage_repair_v1'
CASE=ROOT/'cases/openfoam/stage4f_c_stabilized_restart_lineage_repair_v1/restart4_attempt1'
SOURCE=ROOT/'cases/openfoam/stage4f_c_stabilized_production_hook_v1/branch_P/checkpoints/checkpoint_step00000001_f4a64ff11322.json'

def main()->int:
    RESULT.mkdir(parents=True,exist_ok=True); payload={'status':'failed','source_checkpoint':str(SOURCE),'steps':[]}
    engine=shutdown=None
    try:
        engine,shutdown=build(CASE,SOURCE,'stage18_restart_lineage_probe',2)
        engine.scheduler.bind_restart_source(SOURCE,expected_run_id='stage17_branch_P',expected_next_step=2,expected_next_time_s=1.515)
        for step in range(2,6):
            row=dict(engine(step,1.5075+(step+1)*.0025)); cp=json.loads(Path(row['checkpoint']).read_text(encoding='utf-8'))
            row.update(parent_checkpoint_id=cp['parent_checkpoint_id'],checkpoint_id=cp['checkpoint_id'],time_tick=cp['time_tick'],
                       raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],stabilizer_state=cp['stabilizer_state'])
            payload['steps'].append(row)
        payload.update(status='completed',steps_completed=4)
    except Exception as exc:payload.update(error_type=type(exc).__name__,error=str(exc),steps_completed=len(payload['steps']))
    finally:
        if shutdown:
            try:shutdown()
            except Exception as exc:payload['shutdown_error']=repr(exc)
    atomic_write_json(RESULT/'restart_probe_execution.json',payload)
    return 0 if payload['status']=='completed' else 2
if __name__=='__main__':raise SystemExit(main())
