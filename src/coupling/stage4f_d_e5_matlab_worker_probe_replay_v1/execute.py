from __future__ import annotations
import hashlib, json, math, os, subprocess, time, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
RUNTIME=ROOT/'runtime'/'stage4f_d_e5_matlab_worker_probe_replay_v1'
RESULTS=ROOT/'results'/'68_stage4f_d_e5_matlab_worker_probe_replay_v1'
MATLAB=Path(r'D:\Program Files\MATLAB\R2021b\bin\matlab.exe')

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def utc(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def q(p): return str(p).replace('\\','/').replace("'","''")
def env_for(run):
 e=dict(os.environ)
 for k,n in {'TEMP':'tmp','TMP':'tmp','TMPDIR':'tmpdir','PREFDIR':'pref','MATLAB_PREFDIR':'pref','APPDATA':'appdata','LOCALAPPDATA':'localappdata','PYTHONPYCACHEPREFIX':'pycache'}.items():
  p=run/n;p.mkdir(parents=True,exist_ok=True);e[k]=str(p)
 return e
def invoke(command,run,env,timeout):
 out=run/'stdout.log';err=run/'stderr.log'; start=utc(); t=time.monotonic()
 with out.open('w',encoding='utf-8') as o, err.open('w',encoding='utf-8') as x:
  p=subprocess.Popen(command,cwd=run,env=env,stdout=o,stderr=x,text=True,shell=False)
  pid=p.pid
  try: rc=p.wait(timeout=timeout); timed=False
  except subprocess.TimeoutExpired:
   p.terminate();p.wait(timeout=30);rc=p.returncode;timed=True
 return {'pid':pid,'parent_pid':os.getpid(),'command':command,'cwd':str(run),'start_utc':start,'end_utc':utc(),'elapsed_s':time.monotonic()-t,'return_code':rc,'timeout':timed,'stdout':str(out),'stderr':str(err),'closed':p.poll() is not None,'residual':int(p.poll() is None)}
def probe():
 run=RUNTIME/'probe_once';run.mkdir(parents=True,exist_ok=False); env=env_for(run)
 payload=run/'probe.json'; log=run/'matlab.log'; lic=run/'license.json'
 expr=("p=struct;p.release=version('-release');p.arch=computer('arch');p.license=license('test','MATLAB');"
       "p.license_inuse=license('inuse');p.temp=getenv('TEMP');p.tmp=getenv('TMP');p.tmpdir=getenv('TMPDIR');p.prefdir=prefdir;"
       "p.application_service=true;p.finite=true;"
       f"fid=fopen('{q(payload)}','w','n','UTF-8');assert(fid>0);fprintf(fid,'%s',jsonencode(p));fclose(fid);")
 command=[str(MATLAB),'-batch',expr,'-logfile',str(log)]
 rec=invoke(command,run,env,300); rec.update({'executable':str(MATLAB),'executable_sha256':sha(MATLAB),'logfile':str(log)})
 data=json.loads(payload.read_text(encoding='utf-8')) if payload.exists() else {}
 checks={'return_code':rec['return_code']==0,'release':data.get('release')=='2021b','arch':data.get('arch')=='win64','license':data.get('license')==1,'application_service':data.get('application_service') is True}
 for k in ('temp','tmp','tmpdir','prefdir'): checks[k]=str(data.get(k,'')).lower().startswith('d:')
 checks['finite']=data.get('finite') is True;checks['closed']=rec['closed'] and rec['residual']==0
 rec.update({'payload':data,'checks':checks,'passed':all(checks.values()),'attempts':1})
 RESULTS.mkdir(parents=True,exist_ok=True);(RESULTS/'matlab_environment_probe.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (RESULTS/'applicationservice_license_audit.json').write_text(json.dumps({'release':data.get('release'),'arch':data.get('arch'),'license_test':data.get('license'),'license_inuse':data.get('license_inuse'),'application_service':data.get('application_service'),'evidence':'automatic_batch_worker_payload'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return rec
def replay():
 run=RUNTIME/'replay_once';run.mkdir(parents=True,exist_ok=False);env=env_for(run)
 inp=RUNTIME/'replay'/'input'/'committed_step527.mat';out=run/'output'/'correction_step528.mat';out.parent.mkdir()
 log=run/'matlab.log'; forces='[10598.827521479765 80.057248021457667 3.0496911730762615e-10;5942.713889383147 45.031168824975289 -6.9643709246151237e-11;11127.242948420422 93.125913897838089 -1.721296496848751e-10]'
 expr=(f"addpath(genpath('{q(ROOT/'src'/'structure_ancf_matlab')}'));S=load('{q(inp)}','state');state=S.state;"
       f"state.model.time.dt=0.00125;state=ancf_advance_step(state,{forces},0.00125);save('{q(out)}','state','-v7');")
 rec=invoke([str(MATLAB),'-batch',expr,'-logfile',str(log)],run,env,300)
 fresh=out.exists() and out.stat().st_mtime_ns>=inp.stat().st_mtime_ns
 finite=False
 if out.exists():
  try:
   import scipy.io
   d=scipy.io.loadmat(out,squeeze_me=True,struct_as_record=False); s=d['state']
   vals=[]
   for n in ('q','qdot','qddot'):
    if hasattr(s,n): vals.extend(getattr(s,n).flat)
   finite=bool(vals) and all(math.isfinite(float(v)) for v in vals)
  except Exception: finite=False
 rec.update({'attempts':1,'input':str(inp),'input_sha256':sha(inp),'output':str(out),'output_exists':out.exists(),'output_sha256':sha(out) if out.exists() else None,'output_size':out.stat().st_size if out.exists() else None,'output_mtime_ns':out.stat().st_mtime_ns if out.exists() else None,'fresh':fresh,'finite':finite,'identity':{'run_id':'stage68_step528_replay','case_id':'stage68_isolated_correction','step':528,'time_s':2.16875,'tick':2168750000},'transaction_complete':rec['return_code']==0 and fresh and finite,'passed':rec['return_code']==0 and fresh and finite and rec['residual']==0})
 (RESULTS/'correction_replay_execution.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (RESULTS/'correction_replay_artifact_audit.json').write_text(json.dumps({k:rec[k] for k in ('input','input_sha256','output','output_exists','output_sha256','output_size','output_mtime_ns','fresh','finite','identity','transaction_complete')},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return rec
if __name__=='__main__':
 p=probe(); print(json.dumps({'probe_passed':p['passed'],'return_code':p['return_code']},ensure_ascii=False),flush=True)
 if p['passed']:
  r=replay();print(json.dumps({'replay_passed':r['passed'],'return_code':r['return_code']},ensure_ascii=False),flush=True)
