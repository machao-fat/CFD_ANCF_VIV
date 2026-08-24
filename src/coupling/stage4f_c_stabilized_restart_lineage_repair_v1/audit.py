from __future__ import annotations
import json,math
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json,sha256_file
from .run_probe import ROOT,RESULT,SOURCE

def rel(a,b):return abs(float(a)-float(b))/max(1.,abs(float(a)),abs(float(b)))
def tree(a,b):
    if isinstance(a,dict):return max((tree(a[k],b[k]) for k in a),default=0.)
    if isinstance(a,list):return max((tree(x,y) for x,y in zip(a,b)),default=0.)
    if isinstance(a,(int,float)):return rel(a,b)
    return 0. if a==b else math.inf
def main():
    p=json.loads((ROOT/'results/17_stage4f_c_stabilized_production_hook_v1/branch_P_execution.json').read_text(encoding='utf-8'))['steps']
    r=json.loads((RESULT/'restart_probe_execution.json').read_text(encoding='utf-8'))['steps']; rows=[]; prev=SOURCE.stem
    for expected,actual in zip(p[2:],r):
        a=json.loads(Path(expected['checkpoint']).read_text(encoding='utf-8'));b=json.loads(Path(actual['checkpoint']).read_text(encoding='utf-8'))
        fields=lambda c:[(f['relative_path'],f['sha256']) for s in c['slices'] for f in s['time_files']]
        rows.append({'step':b['step'],'parent':b['parent_checkpoint_id'],'expected_parent':prev,'lineage_ok':b['parent_checkpoint_id']==prev,
          'q_qdot_qddot_error':max(tree(a['structure'][k],b['structure'][k]) for k in ('q','qdot','qddot')),
          'raw_force_error':tree(a['raw_slice_forces_N'],b['raw_slice_forces_N']),'applied_force_error':tree(a['applied_slice_forces_N'],b['applied_slice_forces_N']),
          'stabilizer_error':tree(a['stabilizer_state'],b['stabilizer_state']),'cfd_fields_equal':fields(a)==fields(b),'tick_equal':a['time_tick']==b['time_tick']})
        prev='checkpoint_'+b['checkpoint_id']
    registry=json.loads((ROOT/'cases/openfoam/stage4f_c_stabilized_restart_lineage_repair_v1/restart4_attempt1/owned_process_registry.json').read_text(encoding='utf-8'))
    audit={'status':'passed','rows':rows,'max_state_error':max(x['q_qdot_qddot_error'] for x in rows),'lineage':[SOURCE.stem]+[x['parent_checkpoint_id'] for x in r],
      'max_cfl':max(x['max_cfl'] for x in r),'max_raw_abs_Cd':max(x['max_abs_Cd'] for x in r),'max_applied_abs_Cd':max(abs(f[0])/(500*(50/3)) for x in r for f in x['applied_slice_forces_N']),
      'max_velocity_error':max(x['velocity_difference_over_U'] for x in r),'max_virtual_work_error':max(x['virtual_work_relative_error'] for x in r),
      'max_force_conversion_error':max(x['force_conversion_relative_error'] for x in r),'max_geometry_error_m':max(x['mesh_center_motion_error_m'] for x in r),
      'checkpoint_count':len(r),'schema':'0.2.1+stabilizer.1','owned_started':len(registry),'owned_closed':sum(bool(x.get('end_timestamp')) for x in registry),'owned_residual':sum(not bool(x.get('end_timestamp')) for x in registry),
      'parent_checkpoint_sha256':sha256_file(ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json')}
    audit['passed']=all(x['lineage_ok'] and x['q_qdot_qddot_error']<=1e-11 and x['raw_force_error']==0 and x['applied_force_error']==0 and x['stabilizer_error']==0 and x['cfd_fields_equal'] and x['tick_equal'] for x in rows)
    atomic_write_json(RESULT/'restart_lineage_and_numerical_audit.json',audit);return 0 if audit['passed'] else 2
if __name__=='__main__':raise SystemExit(main())
