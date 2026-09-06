"""Three-slice, no-preCICE construction probe for the motion contract."""
from __future__ import annotations
import json, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from coupling.moving_mesh_openfoam10_case_contract_v1 import ensure_solver_entries,preflight
RUN='implicit_moving_mesh_construction_probe_v1_run_002'; SOURCE=ROOT/'runtime/implicit_one_window_v1_run_001/cases/slice_0000'
def wsl(p):
 s=str(p.resolve()).replace('\\','/'); return '/mnt/'+s[0].lower()+s[2:]
def main():
 runtime=ROOT/'runtime'/RUN
 if runtime.exists(): raise RuntimeError(f'refusing to overwrite {runtime}')
 result={'run_id':RUN,'slices':{}}
 for sid in range(3):
  case=runtime/f'slice_{sid:04d}'; shutil.copytree(SOURCE,case); ensure_solver_entries(case/'system/fvSolution')
  control=(case/'system/controlDict').read_text(); control=control.replace('startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.105;','startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.105;')
  (case/'system/controlDict').write_text(control)
  before=preflight(case,'0.1'); command=f"source /opt/openfoam10/etc/bashrc; cd '{wsl(case)}'; pimpleFoam -noFunctionObjects > construction.stdout 2>&1"
  done=subprocess.run(['wsl.exe','-d','Ubuntu-22.04','--','bash','-lc',command],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=180)
  log=(case/'construction.stdout').read_text(encoding='utf8',errors='replace') if (case/'construction.stdout').is_file() else ''
  ordinary='Solving for cellDisplacement' in log; final='cellDisplacementFinal' in (case/'system/fvSolution').read_text(); result['slices'][str(sid)]={'preflight':before,'return_code':done.returncode,'ordinary_entry_callable':ordinary,'final_entry_present':final,'undefined_keyword':'keyword cellDisplacement is undefined' in log,'patch_mismatch':'inconsistent patch and patchField types' in log,'log':str(case/'construction.stdout')}
 result['MOVING_MESH_CONSTRUCTION_PROBE']='PASS' if all(x['preflight']['MOVING_MESH_CASE_PREFLIGHT']=='PASS' and x['return_code']==0 and not x['undefined_keyword'] and not x['patch_mismatch'] for x in result['slices'].values()) else 'FAIL'
 (runtime/'construction_probe.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps({'MOVING_MESH_CONSTRUCTION_PROBE':result['MOVING_MESH_CONSTRUCTION_PROBE']})); return 0 if result['MOVING_MESH_CONSTRUCTION_PROBE']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
