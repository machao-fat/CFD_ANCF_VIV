from __future__ import annotations
import json,math,os
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from ..stage4f_c_stabilized_production_hook_v1.hook import FrozenLoadStabilizer

ROOT=Path(__file__).resolve().parents[3];RESULT=ROOT/'results/20_stage4f_c_force_freshness_repair_v1'
PARENT=ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json'
LIB=ROOT/'runtime/stage4f_c_stabilized_production_hook_v1/lib/libancfFileMotion.so'; START=1.5075

def build(case,source,run_id,dt,start_step=0,source_run=None):
    plan={'branch':'D2','case_root':str(case),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_full_short_window_v1'),'source_checkpoint':str(source),'dt_s':dt,'start_time_s':START,'end_time_s':1.5575,'steps':40,'slice_ids':[0,1,2],'diagnostic_mode':True}
    os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(LIB);e,shutdown=factory(plan)
    def velocity(predicted,staged):return max(math.hypot(x.vx_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vx_mps'],x.vy_mps-r2._state_motion(e.manifest,e.adapter,staged,x.slice_id,step=x.step,time_s=x.time_s)['vy_mps'])/U_MPS for x in predicted)
    hook=FrozenLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in e.manifest.slices},velocity_auditor=velocity);e.scheduler.stabilization_hook=hook;e.scheduler.run_id=run_id
    payload=json.loads(Path(source).read_text(encoding='utf-8'))
    if payload.get('schema_version')=='0.2.1+stabilizer.1':
        current=float(payload['time_s']);
        for p in e.processes:p.current_time_s=current;p.current_clock_step=start_step
        e.scheduler.stabilizer_state=dict(payload['stabilizer_state']);e.scheduler.previous_slice_forces_N=[list(x) for x in payload['applied_slice_forces_N']];e.scheduler.previous_raw_slice_forces_N=[list(x) for x in payload['raw_slice_forces_N']];e.scheduler.previous_generalized_force=[float(x) for x in payload['previous_generalized_force']];e.expected_step=start_step
        hook.commit(e.scheduler.stabilizer_state);e.scheduler.bind_restart_source(source,expected_run_id=source_run,expected_next_step=start_step,expected_next_time_s=current+dt)
        from ..stage4f_c_stabilized_production_hook_v1.run_restart_probe import align_restart_identity
        align_restart_identity(e,payload,start_step)
    else:
        e.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':e.scheduler.previous_slice_forces_N,'step':2,'time_s':START}));hook.commit(e.scheduler.stabilizer_state)
    return e,shutdown

def gate(row):
    return row['log_passed'] and row['max_cfl']<.8 and row['max_abs_Cd']<=10 and row['velocity_difference_over_U']<=.01 and row['virtual_work_relative_error']<=1e-12 and row['force_conversion_relative_error']<=1e-10
def segment(name,case,source,run_id,dt,start,count,source_run=None):
    out={'status':'failed','branch':name,'steps':[]};e=shutdown=None
    try:
        e,shutdown=build(case,source,run_id,dt,start,source_run)
        for step in range(start,start+count):
            row=dict(e(step,START+(step+1)*dt));cp=json.loads(Path(row['checkpoint']).read_text(encoding='utf-8'));row.update(raw_slice_forces_N=cp['raw_slice_forces_N'],applied_slice_forces_N=cp['applied_slice_forces_N'],stabilizer_state=cp['stabilizer_state'],parent_checkpoint_id=cp['parent_checkpoint_id'],checkpoint_id=cp['checkpoint_id'],time_tick=cp['time_tick'])
            out['steps'].append(row)
            if not gate(row):raise RuntimeError(f'frozen hard gate failed step {step}')
        out.update(status='completed',steps_completed=count)
    except Exception as exc:out.update(error_type=type(exc).__name__,error=str(exc),steps_completed=len(out['steps']))
    finally:
        if shutdown:shutdown()
    atomic_write_json(RESULT/f'{name}_execution.json',out);return out


