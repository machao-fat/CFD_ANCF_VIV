"""Fresh preconditioned 0.1 s coupled smoke. Never launches a longer case."""
from __future__ import annotations
import hashlib, importlib.util, json, math, re, shutil, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from coupling.ancf_newton_evidence_v1 import validate_records
from coupling.generalized_force_metric_v2 import freeze_contract
from coupling.moving_mesh_patch_compatibility_v1.audit import audit as patch_audit
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.openfoam_numerical_quality_contract_v3.audit import evaluate_quality_v3
from coupling.slice_independence_audit_v1.audit import parse_forces,sha256

HERE=Path(__file__).parent; RUN='preconditioned_coupled_0p1s_smoke_v1_run_003'; RUNTIME=ROOT/'runtime'/RUN; RESULTS=ROOT/'results'/RUN
REPORT=ROOT/'docs/preconditioned_coupled_0p1s_smoke_v1/PRECONDITIONED_COUPLED_0P1S_SMOKE_V1_REPORT.md'
STATE=ROOT/'runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json'
PRECURSOR=ROOT/'results/fixed_cylinder_precursor_initialization_contract_v1_run_002/PRECURSOR_STATE_V1'
SOURCE=ROOT/'runtime/generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001/cases/slice_0000'
BASE=ROOT/'tools/three_slice_force_contract_smoke_v1/run_smoke.py'
QUALITY=ROOT/'tools/precursor_transfer_and_structural_mean_load_closure_v1/openfoam_quality_contract_v3.json'
TRANSFER=ROOT/'results/precursor_transfer_and_structural_mean_load_closure_v1_run_001/precursor_transfer_v2_evaluation.json'
DT=.005; OFFSET=.1; STEPS=20; NUM=r'[-+0-9.eE]+'

def put(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',encoding='utf8',newline='\n') as stream: stream.write(text)
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); assert s and s.loader; s.loader.exec_module(m); return m
def contract():
 old=json.loads((ROOT/'tools/generalized_force_metric_v2_and_0p1s_micro_smoke_v1/generalized_force_metric_v2_and_0p1s_micro_smoke_v1_contract.json').read_text())
 old.update({'schema_version':'preconditioned-coupled-0p1s-smoke-v1','run_id':RUN,'case_id':'preconditioned_coupled_0p1s_smoke_v1_case_001','git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'duration_s':.1,'number_of_steps':20,'openfoam_physical_time_offset_s':OFFSET,'initial_structure_state':'NO_FLOW_EQUILIBRIUM','initialization_policy':'zero-geometry precursor state; mean-drag equilibrium explicitly prohibited','quality_contract_v3':{'source':str(QUALITY),'sha256':sha256(QUALITY),'frozen_before_run':True},'precursor_state':{'source':str(PRECURSOR),'manifest_sha256':sha256(PRECURSOR/'manifest.json'),'source_openfoam_time_s':.1,'U_p_phi':'exact manifest hashes','Uf':'OpenFOAM reconstruction','meshPhi':'zero under initial zero motion'},'cold_start_guard':{'raw_first_abs_Fx_max_N':5000.,'basis':'inherited precursor startup-balanced contract'},'structural_startup_sanity_guard':{'max_abs_ux_m':.05,'max_abs_vx_mps':1.,'basis':'10x ANCF-only normal-drag 0.1 s reference (0.004209 m, 0.07482 m/s); runaway screen only'},'mesh_snapshot_coupling_times_s':[0,.025,.05,.075,.1],'formal_status':{'VIV':'not_evaluated','LOCK_IN':'not_evaluated','STROUHAL':'not_evaluated'}})
 old['generalized_force_metric_v2']=freeze_contract(50/16)
 return old
def cfg_xml(base,sid): return base.xml(sid).replace('<max-time value="1"/>','<max-time value="0.1"/>')
def control(base): return base.CONTROL.replace('startFrom startTime; startTime 0; stopAt endTime; endTime 1;','startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.2;')

def prepare():
 if RUNTIME.exists() or RESULTS.exists(): raise RuntimeError('refusing to reuse fresh runtime/results')
 manifest=json.loads((PRECURSOR/'manifest.json').read_text()); c=contract();
 if sha256(STATE)!=c['ANCF']['initial_state']['sha256']: raise RuntimeError('no-flow initial state hash mismatch')
 if manifest.get('status')!='pass': raise RuntimeError('precursor manifest is not pass')
 base=load(BASE,'base_launcher'); base.RUNTIME,base.RESULTS=RUNTIME,RESULTS; base.CONTRACT=HERE/'preconditioned_coupled_0p1s_smoke_v1_contract.json'; base.STATE=STATE
 RUNTIME.mkdir(parents=True)
 put(base.CONTRACT,json.dumps(c,ensure_ascii=False,indent=2)+'\n')
 shutil.copy2(base.CONTRACT,RUNTIME/base.CONTRACT.name)
 cases=[]; hashes={}
 for sid in range(3):
  case=RUNTIME/'cases'/f'slice_{sid:04d}'; shutil.copytree(SOURCE/'constant',case/'constant'); shutil.copytree(SOURCE/'system',case/'system'); (case/'0.1').mkdir(parents=True)
  for field,expected in manifest['field_hashes'].items():
   source=PRECURSOR/field
   if sha256(source)!=expected: raise RuntimeError(f'precursor {field} hash differs from manifest')
   shutil.copy2(source,case/'0.1'/field); hashes.setdefault(field,[]).append(sha256(case/'0.1'/field))
  for field in ('pointDisplacement','cellDisplacement'):
   text=(SOURCE/'0'/field).read_text(encoding='utf8').replace('location "0"','location "0.1"'); put(case/'0.1'/field,text)
  base.ensure_cell_displacement_final(case); put(case/'system/controlDict',control(base)); put(case/'constant/dynamicMeshDict',base.DYNAMIC)
  put(case/'system/preciceDict',f'FoamFile {{ format ascii; class dictionary; object preciceDict; }}\npreciceConfig "precice-config.xml"; participant Fluid_{sid:04d}; modules (FSI); FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1000; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; }} interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cylinder); locations faceCenters; readData (Displacement); writeData (Force); }} }}\n')
  put(case/'precice-config.xml',cfg_xml(base,sid)); cases.append(case)
 (RUNTIME/'logs').mkdir(parents=True); (RUNTIME/'precice-sockets').mkdir()
 pre={str(i):patch_audit(case,field_directory='0.1') for i,case in enumerate(cases)}
 identity={'manifest':manifest,'copied_hashes':hashes,'patch_preflight':pre,'state_sha256':sha256(STATE),'initial_openfoam_time_s':OFFSET,'initial_coupling_time_s':0.0}
 RESULTS.mkdir(parents=True); put(RESULTS/'preflight.json',json.dumps(identity,ensure_ascii=False,indent=2)+'\n')
 if not all(item['MESH_FIELD_PATCH_COMPATIBILITY']=='PASS' for item in pre.values()): raise RuntimeError('MESH_FIELD_PATCH_COMPATIBILITY fail')
 if any(values!=[manifest['field_hashes'][field]]*3 for field,values in hashes.items()): raise RuntimeError('precursor field-copy identity fail')
 return base,cases,c

def points(path): return [[float(x) for x in p] for p in re.findall(r'\(\s*(%s)\s+(%s)\s+(%s)\s*\)'%(NUM,NUM,NUM),path.read_text())]
def vecdist(a,b): return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
def field_centroid(base,case,time,field):
 block=base.patch_block((case/time/field).read_text(),'cylinder'); vs=base.vectors_from_block(block); return [sum(v[i] for v in vs)/len(vs) for i in range(3)] if vs else None
def wsl(path):
 value=str(path.resolve()).replace('\\','/'); return '/mnt/'+value[0].lower()+value[2:]
def mesh_quality(case,time):
 command=f"source /opt/openfoam10/etc/bashrc; cd '{wsl(case)}'; checkMesh -time {time} -allTopology -allGeometry"
 done=subprocess.run(['wsl.exe','-d','Ubuntu-22.04','--','bash','-lc',command],text=True,encoding='utf8',errors='replace',capture_output=True,timeout=90)
 text=done.stdout+'\n'+done.stderr
 def grab(pattern):
  m=re.search(pattern,text,re.I); return float(m.group(1)) if m else None
 return {'return_code':done.returncode,'min_cell_volume':grab(r'Min volume\s*=\s*(%s)'%NUM),'max_non_orthogonality':grab(r'Mesh non-orthogonality Max:\s*(%s)'%NUM),'max_skewness':grab(r'Max skewness\s*=\s*(%s)'%NUM),'negative_volume_count':0 if done.returncode==0 and 'negative volume' not in text.lower() else None,'raw_sha256':hashlib.sha256(text.encode()).hexdigest(),'raw':text}
def loads_by_time(case):
 paths=sorted(case.glob('postProcessing/cylinderForces/*/forces.dat')); 
 if len(paths)!=1: raise RuntimeError(f'force file cardinality {paths}')
 return parse_forces(paths[0]),paths[0]

def audit(base,cases,c,rc):
 rows=[json.loads(line) for line in (RUNTIME/'records.jsonl').read_text().splitlines()] if (RUNTIME/'records.jsonl').exists() else []
 attempts=[json.loads(line) for line in (RUNTIME/'correction_attempts.jsonl').read_text().splitlines()] if (RUNTIME/'correction_attempts.jsonl').exists() else []
 newton=[json.loads(line) for line in (RUNTIME/'newton_evidence.jsonl').read_text().splitlines()] if (RUNTIME/'newton_evidence.jsonl').exists() else []
 summary=json.loads((RUNTIME/'structure_summary.json').read_text()) if (RUNTIME/'structure_summary.json').exists() else {}
 qcon=json.loads(QUALITY.read_text()); quality={str(i):evaluate_quality_v3(audit_log(RUNTIME/'logs'/f'fluid_{i:04d}.stdout',case/'system/fvSolution'),qcon) for i,case in enumerate(cases)}
 forces=[]; forcepaths=[]
 for case in cases:
  f,p=loads_by_time(case); forces.append(f); forcepaths.append(p)
 mesh=[]; snapshots=[]; mesh_ok=True; previous_points={}; mesh_co_proxy=[]
 for step in range(0,STEPS+1):
  tau=step*DT; tof=OFFSET+tau; token=f'{tof:g}' if step else '.1'; token='0.1' if step==0 else token
  for sid,case in enumerate(cases):
   try:
    actual=base.mesh_centroid(case,token); point=field_centroid(base,case,token,'pointDisplacement'); cell=field_centroid(base,case,token,'cellDisplacement')
    expected=[0.,0.,.5] if point is None else [point[0],point[1],.5+point[2]]; err=vecdist(actual,expected); quality_mesh=mesh_quality(case,token)
    current_points=points(case/token/'polyMesh/points')
    increment=None; co_proxy=None
    if sid in previous_points:
     if len(previous_points[sid])!=len(current_points): raise RuntimeError('mesh point count changed unexpectedly')
     increment=max(vecdist(a,b) for a,b in zip(previous_points[sid],current_points))
     h=(quality_mesh['min_cell_volume'] or 0.)**(1/3)
     co_proxy=increment/h if h>0 else math.inf
     mesh_co_proxy.append(co_proxy)
    previous_points[sid]=current_points
    rec={'slice_id':sid,'global_step':step,'tick':int(round(tau*1e9)),'coupling_time_s':tau,'openfoam_physical_time_s':tof,'actual_cylinder_centroid_xyz_m':actual,'received_precice_displacement_xyz_m':point,'cylinder_pointDisplacement_xyz_m':point,'cellDisplacement_cylinder_centroid_xyz_m':cell,'mesh_tracking_error_m':err,'max_point_increment_m':increment,'mesh_courant_proxy_max':co_proxy,'mesh_quality':quality_mesh}
    mesh.append(rec); mesh_ok &= point is not None and err<=1e-8 and quality_mesh['negative_volume_count']==0 and all(quality_mesh[k] is not None for k in ('min_cell_volume','max_non_orthogonality','max_skewness'))
    if any(abs(tau-x)<1e-12 for x in c['mesh_snapshot_coupling_times_s']): snapshots.append(rec)
   except Exception as exc: mesh_ok=False; mesh.append({'slice_id':sid,'global_step':step,'coupling_time_s':tau,'openfoam_physical_time_s':tof,'error':f'{type(exc).__name__}: {exc}'})
 # enrich committed structure/force evidence with both clocks.
 enriched=[]
 for row in rows:
  tau=float(row['time_s']); enriched.append({**row,'coupling_time_s':tau,'openfoam_physical_time_s':OFFSET+tau,'time_relation':'t_OF=0.100 s+tau'})
 put(RESULTS/'coupled_records_with_time_identity.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in enriched))
 first=[]; first_reconciliation=[]
 for sid,data in enumerate(forces):
  item=data.get(.105) or data.get(0.105)
  if item:
   adapter_raw=float(rows[0]['loads'][sid]['openfoam_force_x_N']) if rows else None
   first.append({'slice_id':sid,'pressure_Fx_N':item['pressure_N'][0],'viscous_Fx_N':item['viscous_N'][0],'total_Fx_N':item['total_N'][0],'adapter_received_raw_Fx_N':adapter_raw,'integrated_structural_Fx_N':float(rows[0]['loads'][sid]['force_x_N']) if rows else None})
   first_reconciliation.append(adapter_raw is not None and abs(adapter_raw-item['total_N'][0])<=1e-6)
 forcechain=all(abs(float(l[f'force_{a}_N'])-float(l[f'force_2d_{a}_Npm'])*float(l['slice_length_m']))<=1e-12 for r in rows for l in r['loads'] for a in 'xyz')
 moments=[r['moment_audit'] for r in rows]; mapping=bool(moments) and max(float(x['force_error_absolute_N']) for x in moments)<=1e-8 and max(float(x['moment_error_absolute_Nm']) for x in moments)<=1e-7 and max(float(x['moment_error_normalized_v2']) for x in moments)<=1e-12 and max(float(x['virtual_work']['normalized_error']) for x in moments)<=1e-12
 v2=[a['generalized_force_mapping_v2'] for a in attempts]; v2pass=len(v2)==STEPS and all(x['GENERALIZED_FORCE_MAPPING_V2']=='PASS' for x in v2)
 try: newton_result=validate_records(newton,expected_steps=STEPS)
 except Exception as exc: newton_result={'status':'fail','error':str(exc)}
 ux=[[] for _ in range(3)]; vx=[[] for _ in range(3)]
 for r in rows:
  for sid,m in enumerate(r['motion']): ux[sid].append(abs(float(m['ux_m']))); vx[sid].append(abs(float(m['vx_m'])))
 maxux=[max(x,default=math.inf) for x in ux]; maxvx=[max(x,default=math.inf) for x in vx]
 rawhash=[sha256(p) for p in forcepaths]; field={}
 for tau in (.025,.05,.075,.1):
  token=f'{OFFSET+tau:g}';
  try:
   us=[base.arr(case/token/'U',True) for case in cases]; ps=[base.arr(case/token/'p',False) for case in cases]; field[token]={'U_l2_01':base.l2(us[0],us[1]),'U_l2_02':base.l2(us[0],us[2]),'p_l2_01':base.l2(ps[0],ps[1]),'p_l2_02':base.l2(ps[0],ps[2]),'U_hash':[sha256(case/token/'U') for case in cases],'p_hash':[sha256(case/token/'p') for case in cases]}
  except Exception as exc: field[token]={'error':str(exc)}
 motions_differ=max((vecdist(a['received_precice_displacement_xyz_m'],b['received_precice_displacement_xyz_m']) for a in mesh for b in mesh if a.get('global_step')==b.get('global_step') and a['slice_id']<b['slice_id'] and a.get('received_precice_displacement_xyz_m') is not None and b.get('received_precice_displacement_xyz_m') is not None),default=0.)>1e-8
 conditional_force_independence=(not motions_differ) or len(set(rawhash))==3
 time_identity=all(abs(float(x['openfoam_physical_time_s'])-(OFFSET+float(x['coupling_time_s'])))<=1e-12 for x in enriched)
 checks={'launch_return':rc==0,'committed_20':len(rows)==20 and summary.get('committed_steps')==20,'precursor_transfer_v2':json.loads(TRANSFER.read_text())['PRECURSOR_TRANSFER_V2']=='PASS','cold_start_guard':len(first)==3 and all(abs(x['total_Fx_N'])<=5000 for x in first),'first_force_identity':len(first_reconciliation)==3 and all(first_reconciliation),'force_contract':forcechain,'mapping':mapping,'generalized_force_v2':v2pass,'moving_mesh_tracking':mesh_ok,'quality_v3':all(x['status']=='pass' for x in quality.values()),'newton_40':newton_result.get('status')=='pass' and len(newton)==40,'structural_startup_guard':all(x<=.05 for x in maxux) and all(x<=1 for x in maxvx),'time_offset_identity':time_identity,'conditional_force_independence':conditional_force_independence,'no_participant_fpe_disconnect':rc==0}
 result={'PRECONDITIONED_COUPLED_0P1S_SMOKE':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'windows':len(rows),'first_force':first,'first_force_reconciliation':first_reconciliation,'max_abs_ux_m':maxux,'max_abs_vx_mps':maxvx,'mesh_records':mesh,'mesh_snapshots':snapshots,'quality_v3':quality,'fluid_courant_max':max((float(x.get('max_courant',math.inf)) for x in quality.values()),default=math.inf),'mesh_courant_proxy_max':max(mesh_co_proxy,default=None),'generalized_force_v2_max_utilization':max((float(x['max_threshold_utilization']) for x in v2),default=math.inf),'newton':newton_result,'raw_force_sha256':rawhash,'raw_forces_byte_identical':len(set(rawhash))==1 if len(rawhash)==3 else None,'structure_motions_distinct':motions_differ,'field_independence':field,'first_failing_gate':next((k for k,v in checks.items() if not v),None)}
 put(RESULTS/'gate.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n'); return result
def write_report(result):
 first=result.get('first_force',[]); force='not available' if not first else '; '.join(f"slice {x['slice_id']}: p={x['pressure_Fx_N']:.12g} N, visc={x['viscous_Fx_N']:.12g} N, total={x['total_Fx_N']:.12g} N, integrated={x['integrated_structural_Fx_N']:.12g} N" for x in first)
 mesh=result.get('mesh_records',[]); volumes=[x.get('mesh_quality',{}).get('min_cell_volume') for x in mesh if x.get('mesh_quality',{}).get('min_cell_volume') is not None]; nonorth=[x.get('mesh_quality',{}).get('max_non_orthogonality') for x in mesh if x.get('mesh_quality',{}).get('max_non_orthogonality') is not None]; skew=[x.get('mesh_quality',{}).get('max_skewness') for x in mesh if x.get('mesh_quality',{}).get('max_skewness') is not None]
 lines=['# PRECONDITIONED_COUPLED_0P1S_SMOKE_V1_REPORT','',f"- Run: `{RUN}`",f"- Result: `{result['PRECONDITIONED_COUPLED_0P1S_SMOKE']}`",f"- Windows: `{result.get('windows')}/20`",'- OpenFOAM time identity: `t_OF = 0.100 s + coupling tau`','- Structural initial state: `NO_FLOW_EQUILIBRIUM`; the mean-drag equilibrium was not used.','', '## Startup force','',force,'', '## Gates','']
 lines += [f"- {key}: `{'PASS' if value else 'FAIL'}`" for key,value in result.get('checks',{}).items()]
 lines += ['', '## Observed maxima','',f"- max |ux| per slice [m]: `{result.get('max_abs_ux_m')}`",f"- max |vx| per slice [m/s]: `{result.get('max_abs_vx_mps')}`",f"- min cell volume: `{min(volumes) if volumes else 'not available'}`",f"- max non-orthogonality: `{max(nonorth) if nonorth else 'not available'}`",f"- max skewness: `{max(skew) if skew else 'not available'}`",f"- fluid Courant max: `{result.get('fluid_courant_max')}`",f"- mesh-motion Courant proxy max: `{result.get('mesh_courant_proxy_max')}`",f"- generalized-force V2 max utilization: `{result.get('generalized_force_v2_max_utilization')}`",f"- raw force files byte-identical: `{result.get('raw_forces_byte_identical')}`",f"- structure motions distinct: `{result.get('structure_motions_distinct')}`",'', '## Scope conclusion','', 'No VIV, lock-in, Strouhal, amplitude-convergence, or frequency-convergence conclusion is made from this 0.1 s startup smoke.', f"First failing gate: `{result.get('first_failing_gate')}`."]
 put(REPORT,'\n'.join(lines)+'\n')
def main():
 base,cases,c=prepare(); rc=base.launch(cases)
 try: result=audit(base,cases,c,rc)
 except Exception as exc:
  result={'PRECONDITIONED_COUPLED_0P1S_SMOKE':'FAIL','windows':0,'checks':{'audit_complete':False},'first_failing_gate':'audit_exception','audit_exception':f'{type(exc).__name__}: {exc}'}; put(RESULTS/'gate.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 write_report(result)
 print(json.dumps({'gate':result['PRECONDITIONED_COUPLED_0P1S_SMOKE'],'windows':result['windows'],'blocker':result['first_failing_gate']})); return 0 if result['PRECONDITIONED_COUPLED_0P1S_SMOKE']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
