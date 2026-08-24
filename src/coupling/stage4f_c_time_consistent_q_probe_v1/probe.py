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
from ..stage4f_c_utf8_checkpoint_reader_repair_v1.utf8 import read_json

ROOT=Path(__file__).resolve().parents[3]; RESULT=ROOT/'results/29_stage4f_c_time_consistent_q_probe_v1'; RUN_ID='stage29_probe_Q_utf8_integer_identity_v1'; DT=.00125; STEPS=12
def build(case:Path):
 plan={'branch':'D2','run_id':RUN_ID,'case_root':str(case),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_time_consistent_q_probe_v1'),'source_checkpoint':str(base.PARENT),'dt_s':DT,'start_time_s':base.START,'end_time_s':1.5225,'steps':STEPS,'slice_ids':[0,1,2],'diagnostic_mode':True}; os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(base.LIB); e,shutdown=factory(plan)
 def velocity(predicted,staged): return max(math.hypot(x.vx_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vx_mps'],x.vy_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vy_mps'])/U_MPS for x in predicted)
 hook=TimeConsistentLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in e.manifest.slices},velocity_auditor=velocity); e.scheduler.stabilization_hook=hook; parent=read_json(base.PARENT); current=float(parent['time_s'])
 for p in e.processes:p.current_time_s=current;p.current_clock_step=0
 e.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':parent['previous_slice_forces_N'],'step':2,'time_s':current},run_id=RUN_ID,case_id=e.manifest.case_id));hook.commit(e.scheduler.stabilizer_state);audit_engine(e,RUN_ID);return e,shutdown
def run():
 case=ROOT/'cases/openfoam/stage4f_c_time_consistent_q_probe_v1/probe_Q'; out={'status':'failed','run_id':RUN_ID,'steps':[],'physical_committed_steps':0,'fully_audited_steps':0,'failed_post_commit_step':None,'restart_eligible_checkpoints':[]}; e=shutdown=None
 try:
  e,shutdown=build(case);out['identity_chain']=audit_engine(e,RUN_ID)
  previous_id=None
  for step in range(STEPS):
   expected_tick=1507500000+(step+1)*1250000; row=dict(e(step,base.START+(step+1)*DT)); checkpoint=Path(row['checkpoint'])
   if not row.get('checkpoint_passed') or not checkpoint.is_file():raise RuntimeError('engine did not publish committed checkpoint')
   out['physical_committed_steps']+=1;out['last_physically_committed_checkpoint']=str(checkpoint);atomic_write_json(RESULT/'probe_Q_runner_state.json',out)
   try:
    cp=read_json(checkpoint); state=cp['stabilizer_state']
    if cp.get('status')!='committed' or cp.get('transaction_state')!='committed' or cp.get('step')!=step:raise RuntimeError('Q checkpoint commit identity mismatch')
    if cp['time_tick']!=expected_tick or cp.get('run_id')!=RUN_ID or state.get('run_id')!=RUN_ID or state.get('case_id')!=cp.get('case_id') or state.get('last_step')!=step or state.get('last_time_tick')!=expected_tick:raise RuntimeError('Q integer/state identity mismatch')
    if state.get('tau_decimal')!='0.023728053952574758' or state.get('contract_sha256')!='cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78':raise RuntimeError('Q stabilizer contract mismatch')
    expected_parent=None if step==0 else 'checkpoint_'+str(previous_id)
    if cp.get('parent_checkpoint_id')!=expected_parent:raise RuntimeError('Q checkpoint parent lineage mismatch')
    validate_manifest_transactions(cp['raw_force_snapshot_manifests'],RUN_ID,step,expected_tick)
    for m in cp['raw_force_snapshot_manifests']:
     for key in ('file_size','mtime_ns','global_step','slice_id','integer_tick'):
      if isinstance(m[key],bool) or not isinstance(m[key],int):raise RuntimeError(f'{key} integer roundtrip failed')
    row.update(raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],raw_force_snapshot_manifests=cp['raw_force_snapshot_manifests'],checkpoint_id=cp['checkpoint_id'],parent_checkpoint_id=cp['parent_checkpoint_id'],time_tick=cp['time_tick'],stabilizer_state=cp['stabilizer_state'])
    if not base.gate(row):raise RuntimeError(f'hard gate failed {step}')
   except Exception:out['failed_post_commit_step']=step;atomic_write_json(RESULT/'probe_Q_runner_state.json',out);raise
   previous_id=cp['checkpoint_id'];out['steps'].append(row);out['fully_audited_steps']+=1;out['restart_eligible_checkpoints'].append(str(checkpoint));atomic_write_json(RESULT/'probe_Q_runner_state.json',out)
  out.update(status='completed',steps_completed=STEPS)
 except Exception as exc:out.update(error_type=type(exc).__name__,error=str(exc),steps_completed=out['fully_audited_steps'])
 finally:
  if shutdown:shutdown()
 atomic_write_json(RESULT/'probe_Q_execution.json',out);return out
