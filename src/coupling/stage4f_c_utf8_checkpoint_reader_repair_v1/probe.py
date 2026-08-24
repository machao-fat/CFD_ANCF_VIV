from __future__ import annotations
import math, os
from pathlib import Path
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1.production_hook import TimeConsistentLoadStabilizer
from ..stage4f_c_transaction_identity_repair_v1.identity import audit_engine,validate_manifest_transactions
from ..multi_slice_mapping.mapping import atomic_write_json
from .utf8 import read_json

ROOT=Path(__file__).resolve().parents[3]
RESULT=ROOT/'results/28_stage4f_c_utf8_checkpoint_reader_repair_v1'
RUN_ID='stage28_probe_P_utf8_v1'

def build(case: Path):
 plan={'branch':'D2','run_id':RUN_ID,'case_root':str(case),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_utf8_checkpoint_reader_repair_v1'),'source_checkpoint':str(base.PARENT),'dt_s':.0025,'start_time_s':base.START,'end_time_s':1.5225,'steps':6,'slice_ids':[0,1,2],'diagnostic_mode':True}
 os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(base.LIB); engine,shutdown=factory(plan)
 def velocity(predicted,staged):
  return max(math.hypot(x.vx_mps-r2._state_motion(engine.manifest,engine.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vx_mps'],x.vy_mps-r2._state_motion(engine.manifest,engine.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vy_mps'])/U_MPS for x in predicted)
 hook=TimeConsistentLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in engine.manifest.slices},velocity_auditor=velocity); engine.scheduler.stabilization_hook=hook
 parent=read_json(base.PARENT); current=float(parent['time_s'])
 for process in engine.processes: process.current_time_s=current; process.current_clock_step=0
 engine.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':parent['previous_slice_forces_N'],'step':2,'time_s':current},run_id=RUN_ID,case_id=engine.manifest.case_id)); hook.commit(engine.scheduler.stabilizer_state); audit_engine(engine,RUN_ID)
 return engine,shutdown

def run(*, engine_builder=build, checkpoint_reader=read_json):
 case=ROOT/'cases/openfoam/stage4f_c_utf8_checkpoint_reader_repair_v1/probe_P'
 out={'status':'failed','run_id':RUN_ID,'steps':[],'physical_committed_steps':0,'fully_audited_steps':0,'failed_post_commit_step':None,'restart_eligible_checkpoints':[]}
 engine=shutdown=None
 try:
  engine,shutdown=engine_builder(case); out['identity_chain']=audit_engine(engine,RUN_ID)
  for step in range(6):
   row=dict(engine(step,base.START+(step+1)*.0025)); checkpoint=Path(row['checkpoint'])
   out['physical_committed_steps']+=1; out['last_physically_committed_checkpoint']=str(checkpoint)
   atomic_write_json(RESULT/'probe_P_runner_state.json',out)
   try:
    cp=checkpoint_reader(checkpoint); validate_manifest_transactions(cp['raw_force_snapshot_manifests'],RUN_ID,step,cp['time_tick'])
    for manifest in cp['raw_force_snapshot_manifests']:
     for key in ('file_size','mtime_ns','global_step','slice_id','integer_tick'):
      if isinstance(manifest[key],bool) or not isinstance(manifest[key],int): raise RuntimeError(f'{key} integer roundtrip failed')
    row.update(raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],raw_force_snapshot_manifests=cp['raw_force_snapshot_manifests'],checkpoint_id=cp['checkpoint_id'],parent_checkpoint_id=cp['parent_checkpoint_id'],time_tick=cp['time_tick'])
    if not base.gate(row): raise RuntimeError(f'hard gate failed {step}')
   except Exception:
    out['failed_post_commit_step']=step; atomic_write_json(RESULT/'probe_P_runner_state.json',out); raise
   out['steps'].append(row); out['fully_audited_steps']+=1; out['restart_eligible_checkpoints'].append(str(checkpoint)); atomic_write_json(RESULT/'probe_P_runner_state.json',out)
  out.update(status='completed',steps_completed=6)
 except Exception as exc:
  out.update(error_type=type(exc).__name__,error=str(exc),steps_completed=out['fully_audited_steps'])
 finally:
  if shutdown: shutdown()
 atomic_write_json(RESULT/'probe_P_execution.json',out); return out
