from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT,segment,build
from ..multi_slice_mapping.mapping import atomic_write_json
RESULT=ROOT/'results/48_stage4f_d_e2_case_skeleton_repair_v1'; CASE=ROOT/'cases/openfoam/stage4f_d_e2_case_skeleton_repair_v1'; RUNTIME=ROOT/'runtime/stage4f_d_e2_case_skeleton_repair_v1'
SOURCE=ROOT/'cases/openfoam/stage4f_d_e1_bounded_pilot_v1/block_3/checkpoints/checkpoint_step00000079_e19d01431943.json'; SOURCE_SHA='e14a0552ec6230328208ca1a4a3aafe3e9fb2154a753226c1d93fbba8aa49243'; RUN='stage48_e2_case_skeleton_repair_v1'; CASE_ID='stage48_e2_case_skeleton_repair_v1_3slice'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def contract(): return {'run_id':RUN,'case_id':CASE_ID,'source_checkpoint':str(SOURCE.resolve()),'source_step':79,'seed_time_s':1.6075,'seed_tick':1607500000,'first_predicted_step':80,'dt_s':.00125,'steps':80,'blocks':8,'block_steps':10,'max_wall_clock_s':14400,'max_disk_gb':20,'stabilizer_contract_sha256':'cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78','no_e3':True}
def source_ok(c): return SOURCE.exists() and sha(SOURCE)==SOURCE_SHA and json.loads(SOURCE.read_text(encoding='utf-8-sig')).get('step')==79
def readiness(c):
 if not source_ok(c): return {'passed':False,'reason':'source identity'}
 root=CASE/'readiness_probe_v3'; run=build(root,RUN,c['dt_s'],c['first_predicted_step'],c['seed_time_s'],RUNTIME/'readiness_probe_v3',SOURCE)[0]
 rows=[]
 try:
  for proc in run.cases.values():
   p=Path(proc)
   required=['system/controlDict','system/fvSchemes','system/fvSolution','constant/polyMesh','0','constant/dynamicMeshDict','constant/physicalProperties','constant/momentumTransport','coupling/motion']
   missing=[x for x in required if not (p/x).exists()]
   files=[]
   for x in required:
    q=p/x
    if q.is_file(): files.append({'path':str(q),'size':q.stat().st_size,'mtime_ns':q.stat().st_mtime_ns,'sha256':sha(q)})
   rows.append({'case':str(p),'missing':missing,'files':files,'passed':not missing})
 finally: run.closed=True
 return {'passed':all(x['passed'] for x in rows) and len(rows)==3,'slice_count':len(rows),'slices':rows,'source_sha256':SOURCE_SHA,'seed_time_s':c['seed_time_s'],'seed_tick':c['seed_tick'],'first_predicted_step':80}
def run():
 RESULT.mkdir(parents=True,exist_ok=True); c=contract(); atomic_write_json(RESULT/'case_readiness_contract.json',c)
 CASE.mkdir(parents=True,exist_ok=True); RUNTIME.mkdir(parents=True,exist_ok=True)
 r=readiness(c); atomic_write_json(RESULT/'slice_readiness_audit.json',r)
 if not r['passed']: return {'status':'readiness_failed','readiness':r}
 before=sha(SOURCE); parent=SOURCE; blocks=[]; start=time.monotonic()
 for b in range(8):
  ss=80+b*10; st=1.6075+b*10*.00125; out=segment(f'E2_STAGE48_BLOCK_{b}',RUN,c['dt_s'],ss,10,st,CASE/f'block_{b}',RUNTIME/f'block_{b}',parent); atomic_write_json(RESULT/f'block_{b}_execution.json',out); blocks.append(out)
  if out.get('fully_audited_steps')!=10 or out.get('physical_committed_steps')!=10: return {'status':'failed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE)}
  parent=Path(out['steps'][-1]['checkpoint'])
 result={'status':'completed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE),'wall_clock_s':time.monotonic()-start,'disk_bytes':sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())}; atomic_write_json(RESULT/'E2_execution.json',result); return result
if __name__=='__main__': run()
