"""The sole fresh coupled dt=0.0025 s / 0.100 s diagnostic permitted by V1."""
from __future__ import annotations
import importlib.util,json,math,re,sys,subprocess,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).parent; sys.path.insert(0,str(ROOT/'src'))
from coupling.ancf_newton_evidence_v1 import validate_records
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.slice_independence_audit_v1.audit import parse_forces
from quality_v4 import evaluate_quality_v4
RUN='parallel_explicit_fsi_timestep_stability_v1_run_001'; RUNTIME=ROOT/'runtime'/RUN; RESULTS=ROOT/'results'/RUN
CONTRACT=HERE/'parallel_explicit_fsi_timestep_stability_v1_contract.json'; V4=HERE/'openfoam_quality_contract_v4.json'
BASELINE=ROOT/'runtime/preconditioned_coupled_0p1s_smoke_v1_run_003/records.jsonl'; OUT=ROOT/'docs/parallel_explicit_fsi_timestep_stability_diagnostic_v1/PARALLEL_EXPLICIT_FSI_TIMESTEP_STABILITY_DIAGNOSTIC_V1_REPORT.md'
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); assert s and s.loader; s.loader.exec_module(m); return m
def put(path,value): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def time_key(d,t):
 return next((v for k,v in d.items() if abs(float(k)-t)<1e-9),None)
def containment_monitor(done):
    """Stop only this fresh diagnostic if a pre-frozen containment limit is crossed."""
    limits={'ux_m':.1,'vx_mps':20.,'openfoam_force_x_N':2e6}
    records=RUNTIME/'records.jsonl'; event=RUNTIME/'containment_event.json'
    seen=0
    while not done.wait(.10):
        if not records.is_file(): continue
        lines=records.read_text(encoding='utf8').splitlines()
        for line in lines[seen:]:
            row=json.loads(line); breached=[]
            for sid,motion in enumerate(row['motion']):
                if abs(float(motion['ux_m']))>limits['ux_m']: breached.append({'slice_id':sid,'quantity':'ux_m','value':motion['ux_m'],'limit':limits['ux_m']})
                if abs(float(motion['vx_mps']))>limits['vx_mps']: breached.append({'slice_id':sid,'quantity':'vx_mps','value':motion['vx_mps'],'limit':limits['vx_mps']})
                force=float(row['loads'][sid]['openfoam_force_x_N'])
                if abs(force)>limits['openfoam_force_x_N']: breached.append({'slice_id':sid,'quantity':'raw_Fx_N','value':force,'limit':limits['openfoam_force_x_N']})
            if breached:
                temporary=event.with_suffix(event.suffix+'.tmp')
                with temporary.open('w',encoding='utf8',newline='\n') as stream:
                    stream.write(json.dumps({'global_step':row['global_step'],'tau_s':row['time_s'],'breaches':breached},indent=2)+'\n')
                    stream.flush(); __import__('os').fsync(stream.fileno())
                temporary.replace(event)
                pids=RUNTIME/'pids.txt'
                if pids.is_file():
                    values=re.findall(r'(?:structure_pid|fluid_\d+_pid)=(\d+)', pids.read_text(encoding='utf8'))
                    if values: subprocess.run(['wsl.exe','-d','Ubuntu-22.04','--','bash','-lc',f"kill {' '.join(values)} 2>/dev/null || true"],check=False)
                return
        seen=len(lines)
def main():
 p=load(ROOT/'tools/preconditioned_coupled_0p1s_smoke_v1/run_smoke.py','preconditioned_dt_half')
 p.HERE=HERE; p.RUN=RUN; p.RUNTIME=RUNTIME; p.RESULTS=RESULTS; p.DT=.0025; p.STEPS=40; p.QUALITY=V4
 p.contract=lambda: json.loads(CONTRACT.read_text(encoding='utf8'))
 p.cfg_xml=lambda base,sid: base.xml(sid).replace('<time-window-size value="0.005"/>','<time-window-size value="0.0025"/>').replace('<max-time value="1"/>','<max-time value="0.1"/>')
 def control(base):
  text=base.CONTROL.replace('startFrom startTime; startTime 0; stopAt endTime; endTime 1;','startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.2;')
  return text.replace('deltaT 0.005;','deltaT 0.0025;')
 p.control=control; p.evaluate_quality_v3=evaluate_quality_v4
 base,cases,c=p.prepare(); done=threading.Event(); monitor=threading.Thread(target=containment_monitor,args=(done,),daemon=True); monitor.start()
 try: rc=base.launch(cases)
 finally: done.set(); monitor.join(timeout=1)
 raw=p.audit(base,cases,c,rc)
 rows=[json.loads(x) for x in (RUNTIME/'records.jsonl').read_text(encoding='utf8').splitlines()] if (RUNTIME/'records.jsonl').is_file() else []
 attempts=[json.loads(x) for x in (RUNTIME/'correction_attempts.jsonl').read_text(encoding='utf8').splitlines()] if (RUNTIME/'correction_attempts.jsonl').is_file() else []
 newton=[json.loads(x) for x in (RUNTIME/'newton_evidence.jsonl').read_text(encoding='utf8').splitlines()] if (RUNTIME/'newton_evidence.jsonl').is_file() else []
 qcontract=json.loads(V4.read_text(encoding='utf8')); q={str(i):evaluate_quality_v4(audit_log(RUNTIME/'logs'/f'fluid_{i:04d}.stdout',case/'system/fvSolution'),qcontract) for i,case in enumerate(cases)} if rc==0 else {}
 forces=[]
 for case in cases:
  paths=list(case.glob('postProcessing/cylinderForces/*/forces.dat')); forces.append(parse_forces(paths[0]) if len(paths)==1 else {})
 ledger=[]
 for row in rows:
  tau=float(row['time_s']); tof=.1+tau; step=int(row['global_step']); entry={'step':step,'tau_s':tau,'openfoam_physical_time_s':tof,'slices':[]}
  for sid in range(3):
   rawforce=time_key(forces[sid],tof); load_record=row['loads'][sid]; motion=row['motion'][sid]
   entry['slices'].append({'slice_id':sid,'raw_pressure_Fx_N':None if rawforce is None else rawforce['pressure_N'][0],'raw_viscous_Fx_N':None if rawforce is None else rawforce['viscous_N'][0],'raw_total_Fx_N':None if rawforce is None else rawforce['total_N'][0],'integrated_Fx_N':load_record['force_x_N'],'ux_m':motion['ux_m'],'vx_mps':motion['vx_mps'],'ax_mps2':motion['ax_mps2']})
  ledger.append(entry)
 # Correctness is V2 mapping / V4 quality; legacy absolute-moment remains a diagnostic only.
 try: newton_ok=validate_records(newton,expected_steps=40).get('status')=='pass' and len(newton)==80
 except Exception: newton_ok=False
 mapping_ok=bool(rows) and all(float(r['moment_audit']['force_error_absolute_N'])<=1e-8 and float(r['moment_audit']['moment_error_normalized_v2'])<=1e-12 and float(r['moment_audit']['virtual_work']['normalized_error'])<=1e-12 for r in rows)
 v2_ok=len(attempts)==40 and all(x['generalized_force_mapping_v2']['GENERALIZED_FORCE_MAPPING_V2']=='PASS' for x in attempts)
 first=[time_key(f,.1025) for f in forces]; first_ok=all(x is not None and abs(float(x['total_N'][0]))<=5000 for x in first)
 maxux=[max((abs(float(r['motion'][sid]['ux_m'])) for r in rows),default=math.inf) for sid in range(3)]; maxvx=[max((abs(float(r['motion'][sid]['vx_mps'])) for r in rows),default=math.inf) for sid in range(3)]
 raw_force_values=[abs(float(s['raw_total_Fx_N'])) for e in ledger for s in e['slices'] if s['raw_total_Fx_N'] is not None]
 containment=all(x<=.1 for x in maxux) and all(x<=20 for x in maxvx) and all(x<=2e6 for x in raw_force_values)
 first_identity=all(first[sid] is not None and abs(float(first[sid]['total_N'][0])-float(rows[0]['loads'][sid]['openfoam_force_x_N']))<=1e-6 for sid in range(3)) if rows else False
 checks=raw['checks']; checks.pop('committed_20',None); checks.pop('newton_40',None); checks.pop('quality_v3',None); checks.pop('mesh_quality_every_step_observability',None); checks.pop('structural_startup_guard',None); checks['committed_40']=len(rows)==40; checks['newton_80']=newton_ok; checks['quality_v4']=bool(q) and all(x['status']=='pass' for x in q.values()); checks['mapping_v2']=mapping_ok; checks['generalized_force_v2']=v2_ok; checks['cold_start_guard']=first_ok; checks['first_force_identity']=first_identity; checks['structural_containment']=containment
 # Per-step mesh health is finalized by the separate post-run checkMesh sweep.
 checks['per_step_mesh_health']='PENDING_POSTRUN_SWEEP'
 result={'run_id':RUN,'return_code':rc,'windows':len(rows),'checks':checks,'quality_v4':q,'first_raw_force':first,'ledger':ledger,'max_abs_ux_m':maxux,'max_abs_vx_mps':maxvx,'raw_audit':raw,'status_pre_mesh_sweep':'PASS' if rc==0 and all(v is True for k,v in checks.items() if k!='per_step_mesh_health') else 'FAIL'}
 put(RESULTS/'dt_half_pre_mesh_sweep.json',result); print(json.dumps({'status_pre_mesh_sweep':result['status_pre_mesh_sweep'],'windows':len(rows),'maxvx':maxvx},ensure_ascii=False))
 if result['status_pre_mesh_sweep']!='PASS': raise SystemExit(1)
if __name__=='__main__': main()
