"""One permitted 0.010 s zero-motion dynamic continuation at the new dt."""
from __future__ import annotations
import hashlib,json,re,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).parent; sys.path.insert(0,str(ROOT/'src'))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from quality_v4 import evaluate_quality_v4
from coupling.slice_independence_audit_v1.audit import parse_forces
RUN='parallel_explicit_fsi_timestep_stability_preflight_v1_run_001'; RUNTIME=ROOT/'runtime'/RUN; RESULTS=ROOT/'results'/RUN
SOURCE=ROOT/'runtime/generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001/cases/slice_0000'; PRE=ROOT/'results/fixed_cylinder_precursor_initialization_contract_v1_run_002/PRECURSOR_STATE_V1'; V4=HERE/'openfoam_quality_contract_v4.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,s):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf8',newline='\n') as stream: stream.write(s)
def wsl(p):
    s=str(p.resolve()).replace('\\','/'); return '/mnt/'+s[0].lower()+s[2:]
def main():
 if RUNTIME.exists() or RESULTS.exists(): raise RuntimeError('refusing to reuse preflight runtime/results')
 manifest=json.loads((PRE/'manifest.json').read_text(encoding='utf8'))
 if manifest.get('status')!='pass': raise RuntimeError('precursor state not pass')
 case=RUNTIME/'case'; shutil.copytree(SOURCE/'constant',case/'constant'); shutil.copytree(SOURCE/'system',case/'system'); (case/'0.1').mkdir(parents=True)
 copied={}
 for field,want in manifest['field_hashes'].items():
  src=PRE/field
  if sha(src)!=want: raise RuntimeError(f'precursor hash mismatch: {field}')
  shutil.copy2(src,case/'0.1'/field); copied[field]=sha(case/'0.1'/field)
 for field in ('pointDisplacement','cellDisplacement'):
  put(case/'0.1'/field,(SOURCE/'0'/field).read_text(encoding='utf8').replace('location "0"','location "0.1"'))
 control='''FoamFile { format ascii; class dictionary; object controlDict; }
application pimpleFoam;
startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.11; deltaT 0.0025;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions { cylinderForces { type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }
'''
 put(case/'system/controlDict',control)
 command=f"source /opt/openfoam10/etc/bashrc; cd '{wsl(case)}'; pimpleFoam > preflight.stdout 2>&1"
 done=subprocess.run(['wsl.exe','-d','Ubuntu-22.04','--','bash','-lc',command],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=180)
 put(case/'preflight.launch.stdout',done.stdout or ''); put(case/'preflight.launch.stderr',done.stderr or '')
 paths=list(case.glob('postProcessing/cylinderForces/*/forces.dat'))
 forces=parse_forces(paths[0]) if len(paths)==1 else {}
 rows=[{'time_s':time_s,**value} for time_s,value in sorted(forces.items())]
 advanced=next((r for r in rows if abs(float(r['time_s'])-.1025)<1e-10),None)
 quality=evaluate_quality_v4(audit_log(case/'preflight.stdout',case/'system/fvSolution'),json.loads(V4.read_text(encoding='utf8'))) if done.returncode==0 else {'status':'fail','failures':['pimpleFoam return code']}
 meshphi=case/'0.1025'/'meshPhi'; uf=case/'0.1025'/'Uf'; meshphi_zero=meshphi.is_file() and bool(re.search(r'internalField\s+uniform\s+0\s*;',meshphi.read_text(encoding='utf8')))
 first=float(advanced['total_N'][0]) if advanced else None
 result={'run_id':RUN,'dt_s':.0025,'duration_s':.01,'return_code':done.returncode,'source_hashes_match':copied==manifest['field_hashes'],'first_advanced_raw_Fx_N':first,'cold_start_guard_pass':first is not None and abs(first)<=5000.,'quality_v4':quality,'Uf_reconstructed':uf.is_file(),'meshPhi_zero':meshphi_zero,'PRECURSOR_CONTINUATION_PREFLIGHT':'PASS' if done.returncode==0 and copied==manifest['field_hashes'] and first is not None and abs(first)<=5000. and quality['status']=='pass' and uf.is_file() and meshphi_zero else 'FAIL','force_rows':rows}
 RESULTS.mkdir(parents=True); put(RESULTS/'preflight.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(result,ensure_ascii=False,indent=2))
 if result['PRECURSOR_CONTINUATION_PREFLIGHT']!='PASS': raise SystemExit(1)
if __name__=='__main__': main()
