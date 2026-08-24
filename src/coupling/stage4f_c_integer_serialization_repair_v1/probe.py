from pathlib import Path
import json,math,os
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1.production_hook import TimeConsistentLoadStabilizer
from ..stage4f_c_transaction_identity_repair_v1.identity import audit_engine,validate_manifest_transactions
from ..multi_slice_mapping.mapping import atomic_write_json
ROOT=Path(__file__).resolve().parents[3];RESULT=ROOT/'results/27_stage4f_c_integer_serialization_repair_v1';RUN_ID='stage27_probe_P_exact_integer_v1'
def build(case):
 plan={'branch':'D2','run_id':RUN_ID,'case_root':str(case),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_integer_serialization_repair_v1'),'source_checkpoint':str(base.PARENT),'dt_s':.0025,'start_time_s':base.START,'end_time_s':1.5225,'steps':6,'slice_ids':[0,1,2],'diagnostic_mode':True};os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(base.LIB);e,shutdown=factory(plan)
 def velocity(predicted,staged):return max(math.hypot(x.vx_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vx_mps'],x.vy_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vy_mps'])/U_MPS for x in predicted)
 hook=TimeConsistentLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in e.manifest.slices},velocity_auditor=velocity);e.scheduler.stabilization_hook=hook;p=json.loads(base.PARENT.read_text(encoding='utf-8'));current=float(p['time_s'])
 for x in e.processes:x.current_time_s=current;x.current_clock_step=0
 e.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':p['previous_slice_forces_N'],'step':2,'time_s':current},run_id=RUN_ID,case_id=e.manifest.case_id));hook.commit(e.scheduler.stabilizer_state);audit_engine(e,RUN_ID);return e,shutdown
def run():
 case=ROOT/'cases/openfoam/stage4f_c_integer_serialization_repair_v1/probe_P';out={'status':'failed','run_id':RUN_ID,'steps':[]};e=shutdown=None
 try:
  e,shutdown=build(case);out['identity_chain']=audit_engine(e,RUN_ID)
  for step in range(6):
   row=dict(e(step,base.START+(step+1)*.0025));cp=json.loads(Path(row['checkpoint']).read_text(encoding='utf-8'));validate_manifest_transactions(cp['raw_force_snapshot_manifests'],RUN_ID,step,cp['time_tick']);
   for m in cp['raw_force_snapshot_manifests']:
    for k in ('file_size','mtime_ns','global_step','slice_id','integer_tick'):
     if isinstance(m[k],bool) or not isinstance(m[k],int):raise RuntimeError(f'{k} integer roundtrip failed')
   row.update(raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],raw_force_snapshot_manifests=cp['raw_force_snapshot_manifests'],checkpoint_id=cp['checkpoint_id'],parent_checkpoint_id=cp['parent_checkpoint_id'],time_tick=cp['time_tick']);out['steps'].append(row)
   if not base.gate(row):raise RuntimeError(f'hard gate failed {step}')
  out.update(status='completed',steps_completed=6)
 except Exception as exc:out.update(error_type=type(exc).__name__,error=str(exc),steps_completed=len(out['steps']))
 finally:
  if shutdown:shutdown()
 atomic_write_json(RESULT/'probe_P_execution.json',out);return out
