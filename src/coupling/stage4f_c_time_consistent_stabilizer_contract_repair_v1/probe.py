from __future__ import annotations
import json,math,os
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from .production_hook import TimeConsistentLoadStabilizer
ROOT=Path(__file__).resolve().parents[3]; RESULT=ROOT/'results/25_stage4f_c_time_consistent_stabilizer_contract_repair_v1'; START=1.5075
PARENT=ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json'
LIB=ROOT/'runtime/stage4f_c_stabilized_production_hook_v1/lib/libancfFileMotion.so'
def build(case,run_id,dt):
 plan={'branch':'D2','run_id':run_id,'case_root':str(case),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_time_consistent_stabilizer_contract_repair_v1'),'source_checkpoint':str(PARENT),'dt_s':dt,'start_time_s':START,'end_time_s':1.5225,'steps':12,'slice_ids':[0,1,2],'diagnostic_mode':True}
 os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(LIB);e,shutdown=factory(plan)
 def velocity(predicted,staged):return max(math.hypot(x.vx_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vx_mps'],x.vy_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vy_mps'])/U_MPS for x in predicted)
 hook=TimeConsistentLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in e.manifest.slices},velocity_auditor=velocity);e.scheduler.stabilization_hook=hook
 payload=json.loads(PARENT.read_text(encoding='utf8'));current=float(payload['time_s'])
 for p in e.processes:p.current_time_s=current;p.current_clock_step=0
 e.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':payload['previous_slice_forces_N'],'step':2,'time_s':current},run_id=run_id,case_id=e.manifest.case_id));hook.commit(e.scheduler.stabilizer_state)
 return e,shutdown
def gate(r):return r['log_passed'] and r['max_cfl']<.8 and r['max_abs_Cd']<=10 and r['velocity_difference_over_U']<=.01 and r['virtual_work_relative_error']<=1e-12 and r['force_conversion_relative_error']<=1e-10 and r['mesh_center_motion_error_m']<=1e-12
def run(name,dt,count):
 case=ROOT/'cases/openfoam/stage4f_c_time_consistent_stabilizer_contract_repair_v1'/name;out={'branch':name,'status':'failed','steps':[]};e=shutdown=None
 try:
  e,shutdown=build(case,'stage25_'+name,dt)
  for step in range(count):
   row=dict(e(step,START+(step+1)*dt));cp=json.loads(Path(row['checkpoint']).read_text(encoding='utf8'));row.update(raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],stabilizer_state=cp['stabilizer_state'],raw_force_snapshot_manifests=cp['raw_force_snapshot_manifests'],schema_version=cp['schema_version'],parent_checkpoint_id=cp['parent_checkpoint_id'],checkpoint_id=cp['checkpoint_id'],time_tick=cp['time_tick']);out['steps'].append(row)
   if not gate(row):raise RuntimeError(f'frozen hard gate failed step {step}')
  out.update(status='completed',steps_completed=count)
 except Exception as exc:out.update(error_type=type(exc).__name__,error=str(exc),steps_completed=len(out['steps']))
 finally:
  if shutdown:shutdown()
 atomic_write_json(RESULT/f'{name}_execution.json',out);return out
