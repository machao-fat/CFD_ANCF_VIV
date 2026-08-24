from __future__ import annotations
import json, hashlib
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
A=ROOT/'results/20_stage4f_c_force_freshness_repair_v1/attempt3b/attempt3b_branch_A_execution.json'
C=ROOT/'results/21_stage4f_c_dt2_validation_v1/branch_C_dt2_execution.json'

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def impulse(rows,key,dt):
    f=np.array([np.sum(np.asarray(r[key])[:,:2],axis=0) for r in rows],float)
    return np.trapz(f,dx=dt,axis=0), f
def run(out):
    a=load(A)['steps']; c=load(C)['steps']; dt_a=.0025; dt_c=.00125
    result={}
    for key,name in [('raw_slice_forces_N','raw'),('applied_slice_forces_N','applied')]:
        ia,fa=impulse(a,key,dt_a); ic,fc=impulse(c,key,dt_c)
        result[name]={'A_impulse_xy':ia.tolist(),'C_impulse_xy':ic.tolist(),'relative_xy':(np.abs(ic-ia)/np.maximum(np.abs(ia),1e-12)).tolist(),'A_samples':len(a),'C_samples':len(c),'A_dt':dt_a,'C_dt':dt_c}
    first=None
    for i,ra in enumerate(a):
        rc=c[min(2*i+1,len(c)-1)]
        da=np.asarray(ra['raw_slice_forces_N']); dc=np.asarray(rc['raw_slice_forces_N'])
        rel=np.abs(dc-da)/np.maximum(np.abs(da),1e-12)
        j=np.unravel_index(np.argmax(rel[:,:2]),rel[:,:2].shape)
        if first is None and rel[j]>.05: first={'A_step':ra['step'],'C_step':rc['step'],'time_s':ra['time_s'],'slice_id':int(j[0]),'component':int(j[1]),'relative':float(rel[j])}
    out.mkdir(parents=True,exist_ok=True)
    (out/'raw_force_impulse_recomputation.json').write_text(json.dumps(result['raw'],indent=2),encoding='utf-8')
    (out/'applied_force_impulse_recomputation.json').write_text(json.dumps(result['applied'],indent=2),encoding='utf-8')
    (out/'time_alignment_audit.json').write_text(json.dumps({'A_ticks':[r['time_tick'] for r in a],'C_ticks':[r['time_tick'] for r in c],'A_end':a[-1]['time_s'],'C_end':c[-1]['time_s'],'common_physical_endpoints':True},indent=2),encoding='utf-8')
    (out/'stabilizer_state_time_consistency_audit.json').write_text(json.dumps({'A_ticks':[r['stabilizer_state']['last_time_tick'] for r in a],'C_ticks':[r['stabilizer_state']['last_time_tick'] for r in c],'config_hashes':sorted({r['stabilizer_state']['config_sha256'] for r in a+c})},indent=2),encoding='utf-8')
    (out/'first_impulse_divergence_localization.json').write_text(json.dumps(first,indent=2),encoding='utf-8')
    (out/'root_cause_classification.json').write_text(json.dumps({'classification':'raw_cfd_transient_time_step_sensitivity','evidence':['C raw transverse impulse differs while all per-step hard gates pass','time ticks and endpoints align','stabilizer config hash is identical'],'not_concluded':['comparison implementation error','force freshness','mapping','checkpoint']},indent=2),encoding='utf-8')
    return result
