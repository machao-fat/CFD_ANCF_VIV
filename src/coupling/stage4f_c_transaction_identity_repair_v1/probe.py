from pathlib import Path
import json,math,os
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1.production_hook import TimeConsistentLoadStabilizer
from ..multi_slice_mapping.mapping import atomic_write_json
from .identity import audit_engine,validate_manifest_transactions
ROOT=Path(__file__).resolve().parents[3];RESULT=ROOT/'results/26_stage4f_c_transaction_identity_repair_v1';RUN_ID='stage26_probe_P_exact_tau_v1'
def build(case,dt):
 plan={'branch':'D2','run_id':RUN_ID,'case_root':str(case),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_transaction_identity_repair_v1'),'source_checkpoint':str(base.PARENT),'dt_s':dt,'start_time_s':base.START,'end_time_s':1.5225,'steps':6,'slice_ids':[0,1,2],'diagnostic_mode':True}
 os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(base.LIB);e,shutdown=factory(plan)
 def velocity(predicted,staged):return max(math.hypot(x.vx_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vx_mps'],x.vy_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vy_mps'])/U_MPS for x in predicted)
 hook=TimeConsistentLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in e.manifest.slices},velocity_auditor=velocity);e.scheduler.stabilization_hook=hook
 payload=json.loads(base.PARENT.read_text(encoding='utf8'));current=float(payload['time_s'])
 for p in e.processes:p.current_time_s=current;p.current_clock_step=0
 e.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':payload['previous_slice_forces_N'],'step':2,'time_s':current},run_id=RUN_ID,case_id=e.manifest.case_id));hook.commit(e.scheduler.stabilizer_state);audit_engine(e,RUN_ID);return e,shutdown
def run():
 out={'branch':'probe_P','run_id':RUN_ID,'status':'failed','steps':[]};case=ROOT/'cases/openfoam/stage4f_c_transaction_identity_repair_v1/probe_P_fresh';e=shutdown=None
 try:
  e,shutdown=build(case,.0025);out['identity_chain']=audit_engine(e,RUN_ID)
  for step in range(6):
   row=dict(e(step,base.START+(step+1)*.0025));cp=json.loads(Path(row['checkpoint']).read_text(encoding='utf8'));validate_manifest_transactions(cp['raw_force_snapshot_manifests'],RUN_ID,step,cp['time_tick']);row.update(raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],stabilizer_state=cp['stabilizer_state'],raw_force_snapshot_manifests=cp['raw_force_snapshot_manifests'],schema_version=cp['schema_version'],parent_checkpoint_id=cp['parent_checkpoint_id'],checkpoint_id=cp['checkpoint_id'],time_tick=cp['time_tick']);out['steps'].append(row)
   if not base.gate(row):raise RuntimeError(f'frozen hard gate failed step {step}')
  out.update(status='completed',steps_completed=6)
 except Exception as exc:out.update(error_type=type(exc).__name__,error=str(exc),steps_completed=len(out['steps']))
 finally:
  if shutdown:shutdown()
 atomic_write_json(RESULT/'probe_P_execution.json',out);return out
