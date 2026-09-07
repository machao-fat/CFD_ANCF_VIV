"""Regression for completed-timestep terminal-residual classification."""
from __future__ import annotations
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log

RUN=os.environ.get('QUALITY_V4_COMPLETION_REGRESSION_RUN_ID','formal_implicit_ipc_quality_v4_completion_regression_001')
RESULTS=ROOT/'results'/RUN
HIST=ROOT/'runtime/formal_implicit_projected_initial_state_guard_closure_v1_run_001'
CFD=ROOT/'runtime/formal_implicit_ipc_quality_cfd_only_reproduction_v1_run_002/case'
CONTRACT=ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/openfoam_quality_contract_v4.json'
MODULE=ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/quality_v4.py'

def load():
    spec=importlib.util.spec_from_file_location('quality_v4_completion',MODULE); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(module); return module

def main():
    if RESULTS.exists(): raise RuntimeError('refusing to overwrite quality regression evidence')
    q=load(); contract=json.loads(CONTRACT.read_text(encoding='utf-8'))
    historical=audit_log(HIST/'logs/fluid_0000.stdout',HIST/'cases/slice_0000/system/fvSolution')
    complete=audit_log(CFD/'cfd_only.stdout',CFD/'system/fvSolution')
    historic_result=q.evaluate_quality_v4(historical,contract); complete_result=q.evaluate_quality_v4(complete,contract)
    hrec=historical['time_records'][0]; crec=complete['time_records'][0]
    p_rows=[row for row in crec['solves'] if row['field']=='p']
    passed=(not hrec['physical_timestep_completed'] and historic_result['status']=='fail' and
            historic_result['failures']==['incomplete physical timestep at 0.105'] and
            crec['physical_timestep_completed'] and complete_result['status']=='pass' and
            len(p_rows)==2 and not p_rows[0]['terminal_for_field'] and p_rows[1]['terminal_for_field'])
    result={'QUALITY_V4_COMPLETION_CLASSIFICATION':'PASS' if passed else 'FAIL','historical_incomplete_audit':historical,
            'historical_quality':historic_result,'cfd_only_complete_audit':complete,'cfd_only_quality':complete_result}
    RESULTS.mkdir(parents=True); (RESULTS/'quality_v4_completion_regression.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'QUALITY_V4_COMPLETION_CLASSIFICATION':result['QUALITY_V4_COMPLETION_CLASSIFICATION']},ensure_ascii=False)); return 0 if passed else 1
if __name__=='__main__': raise SystemExit(main())
