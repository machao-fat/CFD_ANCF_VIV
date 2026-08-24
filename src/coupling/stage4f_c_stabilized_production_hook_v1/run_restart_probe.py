from __future__ import annotations
import json,math,os,re
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import U_MPS
from .hook import FrozenLoadStabilizer

ROOT=Path(__file__).resolve().parents[3]; RESULT=ROOT/'results/17_stage4f_c_stabilized_production_hook_v1'
PARENT=ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json'
LIB=ROOT/'runtime/stage4f_c_stabilized_production_hook_v1/lib/libancfFileMotion.so'

def _replace_scalar(path: Path, key: str, value: str) -> None:
    text=path.read_text(encoding='utf-8')
    updated,count=re.subn(rf'(?m)^(\s*{re.escape(key)}\s+)[^;]+;',rf'\g<1>{value};',text)
    if count != 1:
        raise RuntimeError(f'restart dictionary identity field {key} count is {count}: {path}')
    path.write_text(updated,encoding='utf-8')

def align_restart_identity(engine,source_payload,start_step:int)->None:
    expected_time=1.5075+start_step*.0025
    if int(source_payload.get('step',-99)) != start_step-1:
        raise RuntimeError('restart checkpoint step does not precede requested restart step')
    if int(source_payload.get('time_tick',-1)) != round(expected_time*1_000_000_000):
        raise RuntimeError('restart checkpoint integer tick does not match requested restart time')
    if source_payload.get('transaction_state')!='committed':
        raise RuntimeError('restart checkpoint is not a committed transaction')
    for process in engine.processes:
        process.current_time_s=expected_time; process.current_clock_step=start_step
        _replace_scalar(process.case/'system/controlDict','startFrom','startTime')
        _replace_scalar(process.case/'system/controlDict','startTime',format(expected_time,'.12g'))
        _replace_scalar(process.case/'system/controlDict','endTime',format(expected_time+engine.dt_s,'.12g'))
        _replace_scalar(process.case/'constant/dynamicMeshDict','startTime',format(expected_time,'.12g'))
        _replace_scalar(process.case/'constant/dynamicMeshDict','stepOffset',str(start_step))
        metadata_path=process.case/'multi_slice_case_config.json'
        metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
        metadata.update({'start_time_s':expected_time,'restart_global_step':start_step,
                         'restart_time_tick':round(expected_time*1_000_000_000)})
        atomic_write_json(metadata_path,metadata)

def build(case,source,run_id,start_step=0):
    plan={'branch':'D2','case_root':str(case),'results_root':str(RESULT),'runtime_root':str(ROOT/'runtime/stage4f_c_stabilized_production_hook_v1'),
          'source_checkpoint':str(source),'dt_s':.0025,'start_time_s':1.5075,'end_time_s':1.5225,'steps':6,'slice_ids':[0,1,2],'diagnostic_mode':True}
    os.environ['STAGE4F_V3_MOTION_LIBRARY']=str(LIB); engine,shutdown=factory(plan)
    def velocity(predicted,staged):
        return max(math.hypot(r.vx_mps-r2._state_motion(engine.manifest,engine.adapter,staged,r.slice_id,step=r.step,time_s=r.time_s)['vx_mps'],r.vy_mps-r2._state_motion(engine.manifest,engine.adapter,staged,r.slice_id,step=r.step,time_s=r.time_s)['vy_mps'])/U_MPS for r in predicted)
    hook=FrozenLoadStabilizer(slice_force_scales_N={s.slice_id:500*s.slice_length_m for s in engine.manifest.slices},velocity_auditor=velocity)
    engine.scheduler.stabilization_hook=hook; engine.scheduler.run_id=run_id
    source_payload=json.loads(Path(source).read_text(encoding='utf-8'))
    if source_payload.get('schema_version')=='0.2.1+stabilizer.1':
        align_restart_identity(engine,source_payload,start_step)
        engine.scheduler.stabilizer_state=dict(source_payload['stabilizer_state']); engine.scheduler.previous_slice_forces_N=[list(x) for x in source_payload['applied_slice_forces_N']]
        engine.scheduler.previous_raw_slice_forces_N=[list(x) for x in source_payload['raw_slice_forces_N']]
        engine.scheduler.last_committed_step=start_step-1; engine.scheduler.last_committed_time_s=float(source_payload['time_s']); engine.expected_step=start_step
    else:
        engine.scheduler.stabilizer_state=dict(hook.initialize_from_legacy({'previous_slice_forces_N':engine.scheduler.previous_slice_forces_N,'step':2,'time_s':1.5075}))
    hook.commit(engine.scheduler.stabilizer_state); return engine,shutdown

def run():
    payload={'status':'failed','attempt':'attempt2','preserved_attempt1':str(RESULT/'branch_R_restart_execution.json'),
             'first_source_checkpoint':str(RESULT/'branch_R_restart_execution.json'),'first':[],'restart':[]}
    e=s=None
    try:
        attempt1=json.loads((RESULT/'branch_R_restart_execution.json').read_text(encoding='utf-8'))
        if len(attempt1.get('first',[])) != 2:
            raise RuntimeError('preserved restart attempt1 does not contain the accepted first two steps')
        payload['first']=attempt1['first']
        source=Path(payload['first'][-1]['checkpoint'])
        e,s=build(ROOT/'cases/openfoam/stage4f_c_stabilized_production_hook_v1/branch_R_restart4_attempt2',source,'stage17_branch_R',2)
        for step in range(2,6): payload['restart'].append(dict(e(step,1.5075+(step+1)*.0025)))
        p=json.loads((RESULT/'branch_P_execution.json').read_text(encoding='utf-8'))['steps']
        allr=payload['first']+payload['restart']; diffs=[]
        for a,b in zip(p,allr):
            diffs.append({'step':a['step'],'raw_force_equal':a['force_audit']==b['force_audit'],'max_cfl_abs':abs(a['max_cfl']-b['max_cfl']),
                          'velocity_abs':abs(a['velocity_difference_over_U']-b['velocity_difference_over_U'])})
        payload.update(status='completed',steps_completed=6,differences=diffs)
    except Exception as exc: payload.update(error_type=type(exc).__name__,error=str(exc),steps_completed=len(payload['first'])+len(payload['restart']))
    finally:
        if s:s()
    atomic_write_json(RESULT/'branch_R_restart_attempt2_execution.json',payload); return 0 if payload['status']=='completed' else 2
if __name__=='__main__': raise SystemExit(run())
