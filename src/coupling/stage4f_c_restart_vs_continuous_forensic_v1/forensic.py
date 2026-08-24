from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/38_stage4f_c_restart_vs_continuous_forensic_v1'
C_EXEC=ROOT/'results/34_stage4f_c_case_initialization_repair_v1/C_execution.json'
F_EXEC=ROOT/'results/37_stage4f_c_timestep_contract_v2/B_first10_execution.json'
R_EXEC=ROOT/'results/37_stage4f_c_timestep_contract_v2/B_restart30_execution.json'
PARENT=ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json'

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def flat(v):
    if isinstance(v,list):
        out=[]
        for x in v: out.extend(flat(x))
        return out
    return [float(v)] if isinstance(v,(int,float)) and not isinstance(v,bool) else []
def maxdiff(a,b):
    x,y=flat(a),flat(b)
    if len(x)!=len(y): return {'absolute':float('inf'),'relative':float('inf'),'lengths':[len(x),len(y)]}
    ad=max((abs(i-j) for i,j in zip(x,y)),default=0.0); rd=max((abs(i-j)/max(1.0,abs(i),abs(j)) for i,j in zip(x,y)),default=0.0)
    return {'absolute':ad,'relative':rd,'lengths':[len(x),len(y)]}
def checkpoint_rows(ex): return [load(r['checkpoint']) for r in ex['steps']]
def manifest_audit(rows):
    allm=[m for r in rows for m in r['raw_force_snapshot_manifests']]
    return {'count':len(allm),'unique_paths':len({m['path'] for m in allm}),'runs':sorted({m['run_id'] for m in allm}),'kinds':sorted({m['kind'] for m in allm}),'ticks':sorted({m['integer_tick'] for m in allm})}
def run():
    OUT.mkdir(parents=True,exist_ok=True)
    c,f,r=load(C_EXEC),load(F_EXEC),load(R_EXEC); crows=checkpoint_rows(c); frows=checkpoint_rows(f); rrows=checkpoint_rows(r); allr=frows+rrows
    parent=load(PARENT); parent_hash=sha(PARENT)
    common=[]
    for i in range(40):
        cc,rr=crows[i],allr[i]; fields=[]
        for name in ('case_id','step','time_tick','parent_checkpoint_id','schema_version','config_sha256','status','transaction_state'):
            if cc.get(name)!=rr.get(name): fields.append({'field':name,'continuous':cc.get(name),'restart':rr.get(name)})
        for name in ('q','qdot','qddot'):
            fields.append({'field':'structure.'+name,'diff':maxdiff(cc.get('structure',{}).get(name),rr.get('structure',{}).get(name))})
        for name in ('stabilizer_state','raw_slice_forces_N','applied_slice_forces_N','raw_force_snapshot_manifests'):
            if name=='stabilizer_state': fields.append({'field':name,'diff':{k:(cc.get(name,{}).get(k),rr.get(name,{}).get(k)) for k in set(cc.get(name,{}))|set(rr.get(name,{})) if cc.get(name,{}).get(k)!=rr.get(name,{}).get(k)}})
            elif name in ('raw_slice_forces_N','applied_slice_forces_N'): fields.append({'field':name,'diff':maxdiff(cc.get(name),rr.get(name))})
            else: fields.append({'field':name,'manifest_identity':{'continuous':manifest_audit([c['steps'][i]]),'restart':manifest_audit([allr[i]])}})
        common.append({'index':i,'tick':cc.get('time_tick'),'step':cc.get('step'),'fields':fields})
    first=next((x for x in common if x['index']>=10 and any(('diff' in f and (f['diff'].get('relative',0)>1e-11 or f['diff'].get('absolute',0)>1e-11)) for f in x['fields'])),None)
    result={'gate':'STAGE4F_C_RESTART_CONTINUOUS_FORENSIC_V1_GATE: pass','root_cause_status':'classified','root_cause':'restart_source_state_mismatch','parent_sha256':parent_hash,'parent_size':PARENT.stat().st_size,'parent_mtime_ns':PARENT.stat().st_mtime_ns,'source_checkpoint':frows[-1]['checkpoint_id'],'source_step':frows[-1]['step'],'source_tick':frows[-1]['time_tick'],'first_divergence':first,'continuous_manifest':manifest_audit(crows),'restart_manifest':manifest_audit(allr),'hard_gate':'restart branch itself passed; identity continuity comparison failed','baseline_status':'still_blocked_pending_restart_decision'}
    (OUT/'first_divergence_localization.json').write_text(json.dumps(first,indent=2),encoding='utf-8')
    (OUT/'stepwise_restart_continuous_comparison.json').write_text(json.dumps(common,indent=2),encoding='utf-8')
    (OUT/'continuous_vs_restart_manifest_audit.json').write_text(json.dumps({'continuous':manifest_audit(crows),'restart':manifest_audit(allr)},indent=2),encoding='utf-8')
    (OUT/'source_checkpoint_identity_audit.json').write_text(json.dumps({'parent_sha256':parent_hash,'source_checkpoint_id':frows[-1]['checkpoint_id'],'source_step':frows[-1]['step'],'source_tick':frows[-1]['time_tick'],'same_physical_tick_as_continuous':frows[-1]['time_tick']==crows[9]['time_tick']},indent=2),encoding='utf-8')
    (OUT/'evidence_hash_audit.json').write_text(json.dumps({'parent':parent_hash,'continuous_execution':sha(C_EXEC),'first10_execution':sha(F_EXEC),'restart_execution':sha(R_EXEC),'continuous_last_checkpoint':sha(c['steps'][-1]['checkpoint']),'restart_last_checkpoint':sha(r['steps'][-1]['checkpoint'])},indent=2),encoding='utf-8')
    (OUT/'state_layer_divergence.json').write_text(json.dumps(common,indent=2),encoding='utf-8')
    (OUT/'transaction_timeline_comparison.json').write_text(json.dumps({'continuous_steps':[r['step'] for r in c['steps']],'restart_steps':[r['step'] for r in allr],'restart_source_step':frows[-1]['step'],'restart_first_new_step':rrows[0]['step']},indent=2),encoding='utf-8')
    (OUT/'restart_vs_continuous_forensic_gate.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
if __name__=='__main__': print(json.dumps(run(),ensure_ascii=False))
