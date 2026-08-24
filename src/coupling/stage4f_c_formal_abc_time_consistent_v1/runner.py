from __future__ import annotations
import json, math
from pathlib import Path
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1.production_hook import TimeConsistentLoadStabilizer
from ..stage4f_c_transaction_identity_repair_v1.identity import audit_engine,validate_manifest_transactions
from ..stage4f_c_utf8_checkpoint_reader_repair_v1.utf8 import read_json
from ..multi_slice_mapping.mapping import atomic_write_json
ROOT=Path(__file__).resolve().parents[3];RESULT=ROOT/'results/30_stage4f_c_formal_abc_time_consistent_v1';PARENT=base.PARENT
def build(case,run_id,dt,start_step,start_time,runtime,source_checkpoint=None):
 source_checkpoint=source_checkpoint or PARENT
 plan={'branch':'D2','run_id':run_id,'case_root':str(case),'results_root':str(RESULT),'runtime_root':str(runtime),'source_checkpoint':str(source_checkpoint),'dt_s':dt,'start_time_s':start_time,'start_step':start_step,'end_time_s':1.5575,'steps':40,'slice_ids':[0,1,2],'diagnostic_mode':True}
 e,shutdown=factory(plan)
 def velocity(predicted,staged): return max(math.hypot(x.vx_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vx_mps'],x.vy_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vy_mps'])/U_MPS for x in predicted)
 hook=TimeConsistentLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in e.manifest.slices},velocity_auditor=velocity);e.scheduler.stabilization_hook=hook;parent=read_json(source_checkpoint);current=start_time
 # The scheduler step may be an absolute/global identity after restart.  The
 # legacy OpenFOAM motion reader has its own case-local clock, which starts at
 # zero for every freshly materialized restart case.
 for p in e.processes:p.current_time_s=current;p.current_clock_step=0
 e.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':parent['previous_slice_forces_N'],'step':start_step,'time_s':current},run_id=run_id,case_id=e.manifest.case_id));hook.commit(e.scheduler.stabilizer_state);audit_engine(e,run_id);return e,shutdown
def segment(label,run_id,dt,start_step,count,start_time,case,runtime,source_checkpoint=None):
 out={'branch':label,'run_id':run_id,'status':'failed','steps':[],'physical_committed_steps':0,'fully_audited_steps':0,'failed_post_commit_step':None};e=shutdown=None
 try:
  e,shutdown=build(case,run_id,dt,start_step,start_time,runtime,source_checkpoint);out['identity_chain']=audit_engine(e,run_id)
  for step in range(start_step,start_step+count):
   row=dict(e(step,start_time+(step-start_step+1)*dt));cp=read_json(row['checkpoint']);out['physical_committed_steps']+=1
   if cp.get('status')!='committed' or cp.get('step')!=step:raise RuntimeError('formal checkpoint commit identity failure')
   validate_manifest_transactions(cp['raw_force_snapshot_manifests'],run_id,step,cp['time_tick'])
   if cp.get('run_id')!=run_id or cp.get('stabilizer_state',{}).get('contract_sha256')!='cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78':raise RuntimeError('formal identity/contract mismatch')
   row.update(raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],raw_force_snapshot_manifests=cp['raw_force_snapshot_manifests'],checkpoint_id=cp['checkpoint_id'],parent_checkpoint_id=cp.get('parent_checkpoint_id'),time_tick=cp['time_tick'],stabilizer_state=cp['stabilizer_state']);
   if not base.gate(row):raise RuntimeError(f'hard gate failed {step}')
   out['steps'].append(row);out['fully_audited_steps']+=1
 except Exception as exc:out.update(error_type=type(exc).__name__,error=str(exc),failed_post_commit_step=out['fully_audited_steps']+start_step)
 finally:
  if shutdown:shutdown()
 if out['fully_audited_steps']==count:out['status']='completed'
 return out
def run_all():
 outputs={}
 case=ROOT/'cases/openfoam/stage4f_c_formal_abc_time_consistent_v1/A';runtime=ROOT/'runtime/stage4f_c_formal_abc_time_consistent_v1/A';outputs['A']=segment('A','stage30_formal_A_time_consistent_v1',.0025,0,20,base.START,case,runtime);atomic_write_json(RESULT/'A_execution.json',outputs['A'])
 # B is executed only if A passed; its two segments are isolated runtimes and cases.
 if outputs.get('A',{}).get('fully_audited_steps')==20:
  bcase=ROOT/'cases/openfoam/stage4f_c_formal_abc_time_consistent_v1/B_first';br=ROOT/'runtime/stage4f_c_formal_abc_time_consistent_v1/B_first';first=segment('B_first','stage30_formal_B_time_consistent_v1',.0025,0,5,base.START,bcase,br);outputs['B_first']=first
  if first['fully_audited_steps']==5:
   source=Path(first['steps'][-1]['checkpoint']);restart_case=ROOT/'cases/openfoam/stage4f_c_formal_abc_time_consistent_v1/B_restart';second=segment('B_restart','stage30_formal_B_time_consistent_v1',.0025,5,15,1.52,restart_case,ROOT/'runtime/stage4f_c_formal_abc_time_consistent_v1/B_restart',source);outputs['B_restart']=second;outputs['B']={'status':'completed' if second['fully_audited_steps']==15 else 'failed','steps':first['steps']+second['steps'],'physical_committed_steps':first['physical_committed_steps']+second['physical_committed_steps'],'fully_audited_steps':first['fully_audited_steps']+second['fully_audited_steps'],'restart_checkpoint':str(source)}
 if outputs.get('B',{}).get('fully_audited_steps')==20:
  case=ROOT/'cases/openfoam/stage4f_c_formal_abc_time_consistent_v1/C';runtime=ROOT/'runtime/stage4f_c_formal_abc_time_consistent_v1/C';outputs['C']=segment('C','stage30_formal_C_time_consistent_v1',.00125,0,40,base.START,case,runtime);atomic_write_json(RESULT/'C_execution.json',outputs['C'])
 for k,v in outputs.items():atomic_write_json(RESULT/f'{k}_execution.json',v)
 return outputs
