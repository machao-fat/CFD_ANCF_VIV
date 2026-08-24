from __future__ import annotations
import json,math,os
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from .hook import FrozenLoadStabilizer

ROOT=Path(__file__).resolve().parents[3]
CASE=ROOT/'cases/openfoam/stage4f_c_stabilized_production_hook_v1/branch_P'
RESULT=ROOT/'results/17_stage4f_c_stabilized_production_hook_v1'
PARENT=ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json'
LIB=ROOT/'runtime/stage4f_c_stabilized_production_hook_v1/lib/libancfFileMotion.so'

def main()->int:
    plan={'branch':'D2','case_root':str(CASE),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_stabilized_production_hook_v1'),
          'source_checkpoint':str(PARENT),'dt_s':.0025,'start_time_s':1.5075,'end_time_s':1.5225,'steps':6,'slice_ids':[0,1,2],'diagnostic_mode':True}
    os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(LIB); RESULT.mkdir(parents=True,exist_ok=True)
    engine=shutdown=None; payload={'status':'failed','steps':[],'steps_requested':6}
    try:
        engine,shutdown=factory(plan)
        def velocity_audit(predicted,staged):
            gaps=[]
            for record in predicted:
                corrected=r2._state_motion(engine.manifest,engine.adapter,staged,record.slice_id,step=record.step,time_s=record.time_s)
                gaps.append(math.hypot(record.vx_mps-corrected['vx_mps'],record.vy_mps-corrected['vy_mps'])/U_MPS)
            return max(gaps)
        scales={s.slice_id:500.0*s.slice_length_m for s in engine.manifest.slices}
        hook=FrozenLoadStabilizer(slice_force_scales_N=scales,velocity_auditor=velocity_audit)
        engine.scheduler.stabilization_hook=hook; engine.scheduler.run_id='stage17_branch_P'
        legacy={'previous_slice_forces_N':engine.scheduler.previous_slice_forces_N,'step':2,'time_s':1.5075}
        engine.scheduler.stabilizer_state=dict(hook.initialize_from_legacy(legacy)); hook.commit(engine.scheduler.stabilizer_state)
        for step in range(6):
            target=1.5075+(step+1)*.0025
            row=dict(engine(step,target)); checkpoint=json.loads(Path(row['checkpoint']).read_text(encoding='utf-8'))
            row['raw_slice_forces_N']=checkpoint['raw_slice_forces_N']; row['applied_slice_forces_N']=checkpoint['applied_slice_forces_N']; row['stabilizer_state']=checkpoint['stabilizer_state']
            payload['steps'].append(row)
            if not row['log_passed'] or row['max_cfl']>=.8 or row['max_abs_Cd']>10 or row['velocity_difference_over_U']>.01 or row['virtual_work_relative_error']>1e-12 or row['force_conversion_relative_error']>1e-10:
                raise RuntimeError(f'frozen hard gate failed after committed audit at step {step}')
        payload['status']='completed'; payload['steps_completed']=6
    except Exception as exc:
        payload.update(error_type=type(exc).__name__,error=str(exc),steps_completed=len(payload['steps']))
    finally:
        if shutdown:
            try: shutdown()
            except Exception as exc: payload['shutdown_error']=repr(exc)
    atomic_write_json(RESULT/'branch_P_execution.json',payload)
    return 0 if payload['status']=='completed' else 2
if __name__=='__main__': raise SystemExit(main())
