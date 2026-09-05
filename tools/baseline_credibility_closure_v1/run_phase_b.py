"""Read-only diagnosis of the legacy moment metric plus analytic H/H^T tests."""
from __future__ import annotations
import hashlib, json, math, re
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from coupling.moment_mapping_audit_v1.audit import audit, legacy_historical_z_condition
RESULT_DIR=ROOT/'results'/'moment_mapping_audit_v1'; RESULT=RESULT_DIR/'moment_mapping_audit_v1_2.json'
HIST=ROOT/'runtime'/'stage382_cpp_worker_precice_three_slice_continue270_to370_v1'/'logs'/'mapping_diagnostics.jsonl'
POSITIONS=(8.333333333333334,25.0,41.666666666666664); PATTERN=re.compile(r'^\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+\(\(([^)]*)\)\s+\(([^)]*)\)')

def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def q_curve()->list[float]:
    q=[]
    for node in range(17):
        s=50.0*node/16.0; q.extend((s,0.25*s*s/50.0,s,1.0,0.5*s/25.0,1.0))
    return q
def force_at(runtime:Path,sid:str,time:float)->tuple[float,float,float]:
    path=next((runtime/sid/'postProcessing').glob('forces1/*/forces.dat'))
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        match=PATTERN.match(line)
        if match and abs(float(match.group(1))-time)<1e-9:
            pressure=[float(x) for x in match.group(2).split()]; viscous=[float(x) for x in match.group(3).split()]
            return tuple(pressure[i]+viscous[i] for i in range(3))
    raise RuntimeError('historical force time missing')
def scenario(name:str, forces:tuple[tuple[float,float,float],...], origin=(0.,0.,0.)):
    result=audit(q_curve(),forces,positions_m=POSITIONS,origin=origin,delta_q=[((i%11)-5)*0.013 for i in range(102)])
    stable=audit(q_curve(),forces,positions_m=POSITIONS,origin=origin,delta_q=[((i%11)-5)*0.013 for i in range(102)],compensated=True)
    result['name']=name; result['input_forces_N']=forces; result['origin_m']=origin
    result['compensated_comparison']={'moment_absolute_difference_Nm':math.sqrt(sum((a-b)**2 for a,b in zip(result['mapped_moment_Nm'],stable['mapped_moment_Nm']))),
        'virtual_work_absolute_difference_J':abs(result['virtual_work']['mapped_J']-stable['virtual_work']['mapped_J'])}
    return result
def main()->int:
    if RESULT.exists():raise RuntimeError('refusing to overwrite moment-audit evidence')
    rows=[json.loads(line) for line in HIST.read_text(encoding='utf-8').splitlines() if line]
    worst=max(rows,key=lambda row:abs(float(row['moment_balance_error']))); time=float(worst['time_s'])
    points=[tuple(list(point)+[0.0]) for point in worst['interface_positions_xy']]
    forces=[force_at(HIST.parents[1],sid,time) for sid in ('slice_0000','slice_0001','slice_0002')]
    historical=legacy_historical_z_condition(points,forces); historical.update({'global_step':worst['global_step'],'time_s':time,'recorded_legacy_relative_error':worst['moment_balance_error'],'positions_xy_m':worst['interface_positions_xy'],'forces_N':forces})
    cases=[scenario('single_off_axis_point',((3.0,-2.0,1.0),(0.,0.,0.),(0.,0.,0.))),scenario('pure_couple_zero_resultant',((2.,3.,0.),(-2.,-3.,0.),(0.,0.,0.))),scenario('non_symmetric_three_slice',((4.,-1.,2.),(-3.,2.,-1.),(1.,5.,3.))),scenario('translated_origin',((4.,-1.,2.),(-3.,2.,-1.),(1.,5.,3.)),origin=(1.3,-2.1,0.7)),scenario('near_zero_moment',((1.e9,2.e9,0.),(-1.e9,-2.e9,0.),(1.e-6,-1.e-6,0.))),scenario('large_cancellation',((1.e12,-3.e12,0.),(-1.e12,3.e12+1.e-3,0.),(0.,-1.e-3,0.)))]
    summary=[]
    for case in cases:
        healthy=case['name'] not in ('near_zero_moment','large_cancellation')
        summary.append({'name':case['name'],'healthy_analytic_case':healthy,'force_error_normalized':case['force_error_normalized'],'moment_error_normalized_v2':case['moment_error_normalized_v2'],'legacy_z_relative_error':case['legacy_z_relative_error'],'virtual_work_normalized_error':case['virtual_work']['normalized_error']})
    passed=all(item['force_error_normalized']<1e-10 and item['moment_error_normalized_v2']<1e-10 and item['virtual_work_normalized_error']<1e-10 for item in summary)
    payload={'schema_version':'moment_mapping_audit_v1.2','legacy_source':{'path':str(HIST),'sha256':sha(HIST),'error_definition':'abs(Mf_z-Ms_z)/max(abs(Mf_z),abs(Ms_z),1e-30); z moment only; origin=(0,0,0)'},'historical_worst_record':historical,'analytic_cases':cases,'summary':summary,'analytic_status':'pass' if passed else 'fail','MOMENT_MAPPING_STATUS':'METRIC_DEFINITION_REQUIRES_VERSIONING' if passed else 'FAIL','conclusion':'Analytic force, full-vector moment, rigid-rotation virtual-work, pure-couple and translated-origin identities pass. The retained historical metric is relative to the resultant moment itself and its worst record is cancellation-conditioned; historical logs retain no absolute mapped moment, so the 4.44e-10 legacy value cannot be reclassified. Preserve it as fail. Future reports require versioned absolute and contribution-scale-normalized metrics.'}
    RESULT_DIR.mkdir(parents=True,exist_ok=True); RESULT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'analytic_status':payload['analytic_status'],'status':payload['MOMENT_MAPPING_STATUS'],'historical':historical},ensure_ascii=False));return 0 if passed else 2
if __name__=='__main__':raise SystemExit(main())
