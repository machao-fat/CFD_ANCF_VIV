from __future__ import annotations
import json,hashlib,shutil,subprocess,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]; OUT=ROOT/'results/49_stage4f_d_e2_readiness_forensic_v1'; CASE=ROOT/'cases/openfoam/stage4f_d_e2_readiness_forensic_v1'; RUNTIME=ROOT/'runtime/stage4f_d_e2_readiness_forensic_v1'; SRC=ROOT/'cases/openfoam/stage4f_d_e1_bounded_pilot_v1/block_3/checkpoints/checkpoint_step00000079_e19d01431943.json'; SRC_SHA='e14a0552ec6230328208ca1a4a3aafe3e9fb2154a753226c1d93fbba8aa49243'
def sh(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def event(name,status,**kw):
 t=time.time(); row={'stage':name,'status':status,'time_unix':t,**kw}; (OUT/'readiness_progress_events.jsonl').open('a',encoding='utf-8').write(json.dumps(row,ensure_ascii=False)+'\n'); return row
def cmd(args,timeout=20):
 t=time.time()
 try:
  p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout); return {'command':args,'cwd':os.getcwd(),'return_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'elapsed_s':time.time()-t}
 except subprocess.TimeoutExpired as e: return {'command':args,'cwd':os.getcwd(),'return_code':None,'stdout':e.stdout or '','stderr':e.stderr or '','elapsed_s':time.time()-t,'timeout':True}
def main():
 OUT.mkdir(parents=True,exist_ok=True); RUNTIME.mkdir(parents=True,exist_ok=True); CASE.mkdir(parents=True,exist_ok=True)
 if (OUT/'readiness_progress_events.jsonl').exists(): (OUT/'readiness_progress_events.jsonl').unlink()
 stages=[]
 event('case_skeleton_created','start',path=str(CASE)); srcroot=SRC.parent.parent/'cases'
 for i in range(3): shutil.copytree(srcroot/f'slice_{i:04d}',CASE/f'slice_{i:04d}',dirs_exist_ok=True)
 stages.append(event('case_skeleton_created','success',slice_count=3)); event('required_dictionaries','start')
 req=['system/controlDict','system/fvSchemes','system/fvSolution','constant/polyMesh','constant/physicalProperties','constant/momentumTransport','constant/dynamicMeshDict','0']
 audits=[]
 for i in range(3):
  root=CASE/f'slice_{i:04d}'; miss=[x for x in req if not (root/x).exists()]; audits.append({'slice':i,'missing':miss,'passed':not miss,'files':[{'path':str(root/x),'size':(root/x).stat().st_size,'mtime_ns':(root/x).stat().st_mtime_ns,'sha256':sh(root/x)} for x in req if (root/x).is_file()]})
 ok=all(x['passed'] for x in audits); stages.append(event('required_dictionaries','success' if ok else 'failure',audit=audits));
 if not ok: return finish(stages,'do_not_pass','missing dictionary')
 stages.append(event('mesh_initial_fields','start')); ok=all((CASE/f'slice_{i:04d}'/'constant/polyMesh').is_dir() and (CASE/f'slice_{i:04d}'/'1.6075').is_dir() for i in range(3)); stages.append(event('mesh_initial_fields','success' if ok else 'failure'))
 if not ok:return finish(stages,'do_not_pass','mesh/initial field missing')
 stages.append(event('source_checkpoint','start')); ok=SRC.exists() and sh(SRC)==SRC_SHA and json.loads(SRC.read_text(encoding='utf-8-sig')).get('time_tick')==1607500000; stages.append(event('source_checkpoint','success' if ok else 'failure',sha256=sh(SRC)))
 if not ok:return finish(stages,'do_not_pass','source mismatch')
 stages.append(event('motion_payload','start')); motion={'step':80,'time_s':1.60875,'time_tick':1608750000,'run_id':'stage49_e2_readiness_forensic_v1','case_id':'stage49_e2_readiness_forensic_v1_3slice'}; (OUT/'stage49_motion_payload.json').write_text(json.dumps(motion,indent=2),encoding='utf-8'); stages.append(event('motion_payload','success',payload=str(OUT/'stage49_motion_payload.json')))
 stages.append(event('wsl_openfoam_environment','start')); a=cmd(['wsl.exe','-d','Ubuntu-22.04','bash','-lc','source /opt/openfoam10/etc/bashrc; pimpleFoam -help'],20); (OUT/'environment_stdout_stderr.json').write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8'); ok=a.get('return_code')==0 and 'OpenFOAM-10' in a.get('stdout',''); stages.append(event('wsl_openfoam_environment','success' if ok else 'failure',return_code=a.get('return_code')))
 return finish(stages,'pass' if ok else 'environment_blocked','readiness completed without formal E2')
def finish(stages,status,reason):
 out={'gate':status,'reason':reason,'stages':stages,'formal_e2_started':False,'checkpoint_count':0,'force_snapshot_count':0,'source_sha_before':SRC_SHA,'source_sha_after':sh(SRC)}; (OUT/'readiness_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); return out
if __name__=='__main__': print(json.dumps(main(),ensure_ascii=False))
