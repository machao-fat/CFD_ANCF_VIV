"""Generation-only positive/negative regression for the shared motion contract."""
from __future__ import annotations
import json, shutil, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from coupling.moving_mesh_openfoam10_case_contract_v1 import ensure_solver_entries,preflight
RUN='implicit_moving_mesh_case_contract_regression_v1_run_003'
SOURCES={
 'validated_corrected_explicit':ROOT/'runtime/preconditioned_coupled_0p1s_smoke_v1_run_003/cases/slice_0000',
 'precursor_dynamic':ROOT/'runtime/parallel_explicit_fsi_timestep_stability_v1_run_001/cases/slice_0000',
 'dt_half_explicit':ROOT/'runtime/parallel_explicit_fsi_timestep_stability_v1_run_001/cases/slice_0001',
 'implicit_one_window':ROOT/'runtime/implicit_one_window_v1_run_001/cases/slice_0000'}
def main():
 runtime=ROOT/'runtime'/RUN
 if runtime.exists(): raise RuntimeError(f'refusing to overwrite {runtime}')
 runtime.mkdir(parents=True); positive={}
 for label,src in SOURCES.items():
  dst=runtime/label; shutil.copytree(src,dst); ensure_solver_entries(dst/'system/fvSolution'); positive[label]=preflight(dst,'0.1')
 negative={}
 for kind in ('missing_cellDisplacement','missing_cellDisplacementFinal','wrong_patch','wrong_binding'):
  dst=runtime/'negative'/kind; shutil.copytree(runtime/'implicit_one_window',dst)
  if kind.startswith('missing_'):
   name=kind.removeprefix('missing_'); text=(dst/'system/fvSolution').read_text(); text=text.replace(name,name+'Missing',1); (dst/'system/fvSolution').write_text(text)
  elif kind=='wrong_patch':
   field=dst/'0.1/cellDisplacement'; field.write_text(field.read_text().replace('lower { type symmetryPlane; }','lower { type zeroGradient; }'))
  else:
   path=dst/'system/preciceDict'; path.write_text(path.read_text().replace('namePointDisplacement pointDisplacement;','namePointDisplacement unused;'))
  negative[kind]=preflight(dst,'0.1')
 result={'schema_version':'moving-mesh-case-contract-regression-v1','positive':positive,'negative':negative,'CROSS_LAUNCHER_REGRESSION':'PASS' if all(x['MOVING_MESH_CASE_PREFLIGHT']=='PASS' for x in positive.values()) else 'FAIL','NEGATIVE_FAIL_CLOSED':'PASS' if all(x['MOVING_MESH_CASE_PREFLIGHT']=='FAIL' for x in negative.values()) else 'FAIL'}
 (runtime/'case_contract_regression.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps({k:result[k] for k in ('CROSS_LAUNCHER_REGRESSION','NEGATIVE_FAIL_CLOSED')})); return 0 if all(result[k]=='PASS' for k in ('CROSS_LAUNCHER_REGRESSION','NEGATIVE_FAIL_CLOSED')) else 1
if __name__=='__main__': raise SystemExit(main())
