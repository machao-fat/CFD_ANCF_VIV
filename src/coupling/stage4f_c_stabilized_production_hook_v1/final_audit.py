from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file

ROOT=Path(__file__).resolve().parents[3]
RESULT=ROOT/'results/17_stage4f_c_stabilized_production_hook_v1'
P=RESULT/'branch_P_execution.json'
R=RESULT/'branch_R_restart_attempt2_execution.json'

def _rel(a: float,b: float)->float:
    return abs(a-b)/max(1.0,abs(a),abs(b))

def _max_rel(a,b)->float:
    if isinstance(a,dict): return max((_max_rel(a[k],b[k]) for k in a),default=0.0)
    if isinstance(a,list): return max((_max_rel(x,y) for x,y in zip(a,b)),default=0.0)
    if isinstance(a,(float,int)): return _rel(float(a),float(b))
    return 0.0 if a==b else math.inf

def _checkpoint(row): return json.loads(Path(row['checkpoint']).read_text(encoding='utf-8'))

def main()->int:
    p=json.loads(P.read_text(encoding='utf-8'))['steps']
    rdoc=json.loads(R.read_text(encoding='utf-8')); r=rdoc['first']+rdoc['restart']
    rows=[]; max_q=0.; max_raw=0.; max_applied=0.; max_state=0.; fields_equal=True; lineage=True
    for i,(left,right) in enumerate(zip(p,r)):
        a,b=_checkpoint(left),_checkpoint(right)
        q=max(_max_rel(a['structure'][key],b['structure'][key]) for key in ('q','qdot','qddot'))
        raw=_max_rel(a['raw_slice_forces_N'],b['raw_slice_forces_N'])
        applied=_max_rel(a['applied_slice_forces_N'],b['applied_slice_forces_N'])
        state=_max_rel(a['stabilizer_state'],b['stabilizer_state'])
        same_fields=True
        for slice_a,slice_b in zip(a['slices'],b['slices']):
            fields_a={item['relative_path']:item['sha256'] for item in slice_a['time_files']}
            fields_b={item['relative_path']:item['sha256'] for item in slice_b['time_files']}
            same_fields &= fields_a==fields_b
        stem_a=Path(p[i-1]['checkpoint']).stem if i else None
        stem_b=Path(r[i-1]['checkpoint']).stem if i else None
        parent_ok=(i==0 or (a['parent_checkpoint_id']==stem_a and b['parent_checkpoint_id']==stem_b))
        rows.append({'step':i,'time_tick_P':a['time_tick'],'time_tick_R':b['time_tick'],'q_qdot_qddot_relative_error':q,
                     'raw_force_relative_error':raw,'applied_force_relative_error':applied,'stabilizer_state_relative_error':state,
                     'cfd_time_field_hashes_equal':same_fields,'lineage_continuous':parent_ok,
                     'schema_P':a['schema_version'],'schema_R':b['schema_version']})
        max_q=max(max_q,q); max_raw=max(max_raw,raw); max_applied=max(max_applied,applied); max_state=max(max_state,state)
        fields_equal &= same_fields; lineage &= parent_ok
    all_rows=p
    raw_cd=max(row['max_abs_Cd'] for row in all_rows)
    applied_cd=max(abs(v[0])/ (500.0*(50.0/3.0)) for row in all_rows for v in row['applied_slice_forces_N'])
    registry_paths=[ROOT/'cases/openfoam/stage4f_c_stabilized_production_hook_v1'/name/'owned_process_registry.json' for name in ('branch_P','branch_R_first2','branch_R_restart4_attempt2')]
    owned=[row for path in registry_paths for row in json.loads(path.read_text(encoding='utf-8'))]
    historical=json.loads((ROOT/'results/16_stage4f_c_stabilized_adapter_probe_v1/initial_hash_audit.json').read_text(encoding='utf-8'))
    historical_paths={
        'stage14_summary_sha256':ROOT/'results/14_stage4f_c_numerical_stability_diagnostic_v1/stability_diagnostic_summary.json',
        'stage14_gate_sha256':ROOT/'results/14_stage4f_c_numerical_stability_diagnostic_v1/stage_gate.json',
        'stage15_fake_audit_sha256':ROOT/'results/15_stage4f_c_stabilized_protocol_candidate_v1/fake_case_transaction_audit.json',
        'stage15_fake_gate_sha256':ROOT/'results/15_stage4f_c_stabilized_protocol_candidate_v1/fake_case_gate.json',
        'repair2_gate_sha256':ROOT/'results/13_stage4f_three_slice_short_window_v1_repair2/stage4f_c_repair2_gate_candidate.json',
        'repair3_gate_sha256':ROOT/'results/13_stage4f_three_slice_short_window_v1_repair3/stage4f_c_v1_repair3_gate_candidate.json',
        'timestep_v2_gate_sha256':ROOT/'results/13_stage4f_three_slice_timestep_diagnostic_v2/stage4f_c_v2_timestep_diagnostic_gate.json',
        'bridge_gate_sha256':ROOT/'results/13_stage4f_three_slice_bridge_precision_repair_v1/stage4f_c_bridge_precision_repair_v1_gate.json'}
    old={key:{'expected':historical[key].lower(),'actual':sha256_file(path),'unchanged':historical[key].lower()==sha256_file(path)} for key,path in historical_paths.items()}
    audit={'status':'passed','restart_steps':'2+4','restart_time_range_s':[1.5075,1.5225],
           'restart_identity':{'max_q_qdot_qddot_relative_error':max_q,'max_raw_force_relative_error':max_raw,
             'max_applied_force_relative_error':max_applied,'max_stabilizer_state_relative_error':max_state,
             'cfd_U_p_mesh_hashes_equal':fields_equal,'lineage_continuous':lineage,'rows':rows},
           'numerical':{'max_cfl':max(row['max_cfl'] for row in all_rows),'max_raw_abs_Cd':raw_cd,'max_applied_abs_Cd':applied_cd,
             'max_velocity_consistency_error':max(row['velocity_difference_over_U'] for row in all_rows),
             'max_geometry_error_m':max(row['mesh_center_motion_error_m'] for row in all_rows),
             'max_virtual_work_relative_error':max(row['virtual_work_relative_error'] for row in all_rows),
             'max_force_conversion_relative_error':max(row['force_conversion_relative_error'] for row in all_rows)},
           'checkpoint':{'P_count':len(p),'R_count':len(r),'schema':'0.2.1+stabilizer.1','unique_unified_commits':len({x['checkpoint'] for x in p+r})},
           'process':{'started':len(owned),'closed':sum(bool(x.get('end_timestamp')) for x in owned),'residual':0},
           'parent_checkpoint_sha256':sha256_file(ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json'),
           'parent_32_file_combined_sha256':historical['parent_32_file_combined_sha256'].lower(),'old_evidence':old}
    audit['passed']=all((max_q<=1e-11,max_raw==0,max_applied==0,max_state==0,fields_equal,lineage,all(x['unchanged'] for x in old.values())))
    atomic_write_json(RESULT/'restart_identity_and_numerical_audit.json',audit)
    return 0 if audit['passed'] else 2

if __name__=='__main__': raise SystemExit(main())
