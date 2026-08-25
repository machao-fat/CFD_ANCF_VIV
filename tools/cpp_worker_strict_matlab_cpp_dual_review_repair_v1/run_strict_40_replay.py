"""Run the repaired C++ worker against the fresh step559->599 MATLAB golden."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from scipy.io import loadmat

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'src'))
from tools.cpp_worker_persistent_ipc_v1.run_matlab_cpp_dual_run_40 import main as run_dual

SOURCE=ROOT/'cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json'
SEED=ROOT/'runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat'
TEMPLATE=ROOT/'runtime/cpp_worker_persistent_ipc_v1/dual_run_024/results/cpp_input_fixture.json'

def write_fixture(path:Path)->None:
    source=json.loads(SOURCE.read_text(encoding='utf-8')); fixture=json.loads(TEMPLATE.read_text(encoding='utf-8'))
    mat=loadmat(SEED,squeeze_me=True,struct_as_record=False)['state']
    fixture.update({'source_step':559,'source_time_s':2.2075,'q':source['structure']['q'],'qdot':source['structure']['qdot'],'qddot':source['structure']['qddot'],'slice_force':[v for row in source['previous_slice_forces_N'] for v in row],'gauss_order':5,'max_newton':50,'mass_matrix':[float(v) for v in mat.model.mass_matrix.reshape(-1)]})
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(fixture,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--golden',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--results',type=Path,required=True);p.add_argument('--worker',type=Path,required=True);a=p.parse_args()
    if a.runtime.exists() or a.results.exists(): raise SystemExit('fresh runtime/results required')
    a.runtime.mkdir(parents=True); a.results.mkdir(parents=True); fixture=a.runtime/'cpp_input_fixture_step559.json'; write_fixture(fixture)
    normalized=a.runtime/'matlab_golden_40_normalized.jsonl'
    with a.golden.open(encoding='utf-8') as source, normalized.open('w',encoding='utf-8') as target:
        for line in source:
            record=json.loads(line); record['integer_tick']=int(round(float(record['integer_tick']))); target.write(json.dumps(record,separators=(',',':'))+'\n')
    return run_dual(str(fixture),str(normalized),str(a.results/'matlab_cpp_dual_run_40_audit.json'),str(a.worker))
if __name__=='__main__': raise SystemExit(main())
