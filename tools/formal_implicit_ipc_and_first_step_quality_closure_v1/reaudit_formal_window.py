"""Read-only V4 re-audit of a completed implicit window with repeated OF time."""
from __future__ import annotations
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log

FORMAL_RUN='formal_implicit_ipc_and_first_step_quality_closure_v1_run_001'
RUN=os.environ.get('FORMAL_WINDOW_REAUDIT_RUN_ID','formal_implicit_ipc_and_first_step_quality_closure_v1_reaudit_001')
RUNTIME=ROOT/'runtime'/FORMAL_RUN; RESULTS=ROOT/'results'/RUN
MODULE=ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/quality_v4.py'
CONTRACT=ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/openfoam_quality_contract_v4.json'

def main():
    if RESULTS.exists(): raise RuntimeError('refusing to overwrite re-audit evidence')
    spec=importlib.util.spec_from_file_location('formal_reaudit_quality_v4',MODULE); mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod)
    contract=json.loads(CONTRACT.read_text(encoding='utf-8'))
    per_slice={}
    for sid in range(3):
        audit=audit_log(RUNTIME/'logs'/f'fluid_{sid:04d}.stdout',RUNTIME/'cases'/f'slice_{sid:04d}'/'system'/'fvSolution')
        per_slice[str(sid)]={'quality_v4':mod.evaluate_quality_v4(audit,contract),'time_records':[
            {'time_s':row['time_s'],'physical_trial_index':row['physical_trial_index'],'completed':row['physical_timestep_completed']} for row in audit['time_records']]}
    old=json.loads((ROOT/'results'/FORMAL_RUN/'formal_one_window_gate.json').read_text(encoding='utf-8'))
    non_quality={key:value for key,value in old['checks'].items() if key!='quality_v4'}
    pass_reaudit=all(non_quality.values()) and all(row['quality_v4']['status']=='pass' for row in per_slice.values())
    result={'FORMAL_IMPLICIT_ONE_WINDOW_REAUDIT':'PASS' if pass_reaudit else 'FAIL','source_formal_runtime':str(RUNTIME),
            'historical_formal_gate_immutable':old['FORMAL_IMPLICIT_ONE_WINDOW'],'historical_quality_gate_immutable':old['checks']['quality_v4'],
            'quality_v4_reaudit':per_slice,'non_quality_checks':non_quality,
            'interpretation':'read-only re-evaluation under parser 1.0.3; no historical gate artifact was modified'}
    RESULTS.mkdir(parents=True); (RESULTS/'formal_window_quality_v4_reaudit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'FORMAL_IMPLICIT_ONE_WINDOW_REAUDIT':result['FORMAL_IMPLICIT_ONE_WINDOW_REAUDIT']},ensure_ascii=False)); return 0 if pass_reaudit else 1
if __name__=='__main__': raise SystemExit(main())
