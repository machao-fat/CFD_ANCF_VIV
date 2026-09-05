from __future__ import annotations
import importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from coupling.moving_mesh_patch_compatibility_v1.audit import audit
BASE=ROOT/'tools/corrected_moving_mesh_coupling_revalidation_v1/run_revalidation.py'; HERE=Path(__file__).parent; CONTRACT=HERE/'moving_mesh_patch_consistency_fix_and_1s_retry_v1_contract.json'; RUNTIME=ROOT/'runtime/moving_mesh_patch_consistency_1s_retry_v1_run_001'; RESULTS=ROOT/'results/moving_mesh_patch_consistency_1s_retry_v1_run_001'; V1=ROOT/'tools/three_slice_force_contract_smoke_v1/run_smoke.py'
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);assert s.loader;s.loader.exec_module(m);return m
def main():
 if RUNTIME.exists() or RESULTS.exists():raise RuntimeError('refusing to reuse retry runtime')
 if not CONTRACT.is_file():raise RuntimeError('frozen contract missing')
 base=load(BASE,'corrected_revalidation'); launcher=base.load_launcher(RUNTIME,RESULTS,CONTRACT,1.0); cases=launcher.prepare(); pre={str(i):audit(case) for i,case in enumerate(cases)}; RESULTS.mkdir(parents=True,exist_ok=True);(RESULTS/'mesh_field_patch_compatibility_preflight.json').write_text(json.dumps(pre,ensure_ascii=False,indent=2)+'\n')
 if not all(x['MESH_FIELD_PATCH_COMPATIBILITY']=='PASS' for x in pre.values()):
  (RESULTS/'gate.json').write_text(json.dumps({'gate':'FAIL','blocker':'MESH_FIELD_PATCH_COMPATIBILITY','preflight':pre},ensure_ascii=False,indent=2)+'\n');return 1
 # The compatibility audit is the construction preflight: it reads every
 # field named by the actual mover plus adapter configuration before CFD.
 (RESULTS/'openfoam_construction_preflight.json').write_text(json.dumps({'status':'PASS','method':'authoritative generated dictionary and polyMesh boundary compatibility audit','slices':pre,'no_physical_time_advanced':True},ensure_ascii=False,indent=2)+'\n')
 result=base.audit(RUNTIME,RESULTS,CONTRACT,launcher.launch(cases));result['MESH_FIELD_PATCH_COMPATIBILITY']='PASS';result['CORRECTED_COUPLED_1S_SMOKE']='PASS' if result['gate']=='PASS' else 'FAIL';(RESULTS/'gate.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'gate':result['gate']}));return 0 if result['gate']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
