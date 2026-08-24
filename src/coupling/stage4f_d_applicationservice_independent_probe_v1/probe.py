from __future__ import annotations
import hashlib,json,os,subprocess,uuid
from datetime import datetime,timezone
from pathlib import Path
from .validator import validate,classify
ROOT=Path(__file__).resolve().parents[3]; R=ROOT/'runtime'/'stage4f_d_applicationservice_independent_probe_v1'; O=ROOT/'results'/'69_stage4f_d_applicationservice_independent_probe_v1'
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def run():
 R.mkdir(parents=True,exist_ok=True); O.mkdir(parents=True,exist_ok=True); run=R/'probe_once';run.mkdir(exist_ok=False)
 rid='stage69_service_probe_'+uuid.uuid4().hex[:10]; req=uuid.uuid4().hex; start=now()
 # Read-only Windows service/process/event queries. No MATLAB or worker is launched.
 ps="Get-Service -ErrorAction SilentlyContinue | Where-Object {$_.Name -match 'MathWorks|MATLAB|Application'} | Select Name,Status,StartType | ConvertTo-Json -Compress"
 ev="Get-WinEvent -LogName Application -MaxEvents 100 -ErrorAction SilentlyContinue | Where-Object {$_.ProviderName -match 'MathWorks|MATLAB'} | Select TimeCreated,Id,ProviderName,LevelDisplayName,Message | ConvertTo-Json -Compress"
 proc="Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -match 'MATLAB|MathWorks|ApplicationService|Connector|EditorData'} | Select Id,ProcessName,StartTime,Path | ConvertTo-Json -Compress"
 records={}
 for n,c in [('services',ps),('events',ev),('processes',proc)]:
  p=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',c],capture_output=True,text=True,timeout=30); (run/(n+'.stdout')).write_text(p.stdout,encoding='utf-8');(run/(n+'.stderr')).write_text(p.stderr,encoding='utf-8');records[n]={'return_code':p.returncode,'stdout':str(run/(n+'.stdout')),'stderr':str(run/(n+'.stderr'))}
 end=now(); evidence={'probe_run_id':rid,'runtime':str(run),'request_id':req,'request_timestamp':start,'response_timestamp':None,'response_id':None,'response_payload_hash':None,'service_pid':None,'independent_response':False,'independent_process':False,'independent_event':False,'time_aligned':False,'service_probe_unavailable':True,'matlab_started':0,'worker_replay_started':0,'openfoam_started':0,'wsl_started':0,'records':records,'start_utc':start,'end_utc':end,'classification':'service_probe_unavailable','gate':'do_not_pass'}
 (O/'applicationservice_probe_execution.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return evidence
if __name__=='__main__': print(json.dumps(run(),ensure_ascii=False,indent=2))
