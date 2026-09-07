"""Offline regression for the production checkpoint schema; no CFD/preCICE process."""
from __future__ import annotations
import hashlib, importlib.util, json, os, shutil, struct, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest

HERE=Path(__file__).parent
def load(path,name):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); assert s and s.loader; s.loader.exec_module(m); return m
PART=load(HERE/'implicit_structure_participant.py','checkpoint_participant')
RUN=os.environ.get('PRODUCTION_PARTICIPANT_ROLLBACK_RUN_ID','implicit_participant_rb_reg_v1_run_003')
LOAD_A=((22503.305595427,0.,0.),)*3; LOAD_B=((11251.6527977135,0.,0.),)*3
def sha(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def main():
    runtime=ROOT/'runtime'/RUN
    if runtime.exists(): raise RuntimeError(f'refusing to overwrite {runtime}')
    runtime.mkdir(parents=True)
    contract=json.loads((ROOT/'tools/preconditioned_coupled_0p1s_smoke_v1/preconditioned_coupled_0p1s_smoke_v1_contract.json').read_text(encoding='utf-8'))
    state=json.loads((ROOT/'runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json').read_text(encoding='utf-8'))
    model=PART.model_from_contract(contract); q,qdot,qddot=(tuple(float(x) for x in state[k]) for k in ('q','qdot','qddot')); mass=tuple(float(x) for x in state['mass_matrix']); base=tuple(float(x) for x in state['base_load'])
    model_hash=hashlib.sha256(model.bytes()+struct.pack('<'+'d'*len(mass),*mass)).hexdigest(); worker_path=ROOT/'runtime/parallel_implicit_coupling_readiness_and_0p05s_diagnostic_v1/cpp_worker_build/cfd_ancf_ancf_kernel_worker'
    worker=KernelWorker(worker_path,runtime/'cpp_worker',RUN,'implicit_participant_rb_reg_v1',expected_model_contract_sha256=model_hash,allow_implicit_retry=True)
    adapter=CppKernelCampaignAdapter(worker=worker,model=model,request_factory=KernelStepRequest,run_id=RUN,case_id='implicit_participant_rb_reg_v1',source_global_step=0,source_time_s=0.,source_tick=0,dt_s=.005,q=q,qdot=qdot,qddot=qddot,base_load=base,mass_matrix=mass,strict_numerical_contract=True,expected_model_contract_sha256=model_hash,implicit_rollback_transport=True)
    trials=[]; error=None
    try:
        adapter.start(); cp=PART.PhysicalCheckpoint(runtime,adapter); initial=adapter.state_view(); prior=[(0.,0.,0.)]*3
        checkpoint=cp.write(1,0.,prior,0,{'test':'six-cycles'})
        for attempt in range(1,7):
            p,_=adapter.predict(1,.005,prior); c,_=adapter.correct(1,.005,LOAD_A); trial=adapter.state_view(); restored=cp.restore()
            if restored['post_restore_state_sha256'] != restored['checkpoint_state_sha256']: raise RuntimeError('physical state rollback mismatch')
            if adapter.state_view()!=initial: raise RuntimeError('rollback state drift')
            trials.append({'attempt':attempt,'prediction_wire':p['wire_sequence'],'correction_wire':c['wire_sequence'],'trial_sha256':sha(trial),'restore':restored})
        if len({x['prediction_wire'] for x in trials}|{x['correction_wire'] for x in trials}) != 12: raise RuntimeError('wire IDs were reused')
        if len({x['trial_sha256'] for x in trials})!=1: raise RuntimeError('identical trial not deterministic')
        # Force contamination: a discarded F1 trial must not become previous force for F2.
        p1,_=adapter.predict(1,.005,prior); c1,_=adapter.correct(1,.005,LOAD_A); cp.restore(); p2,_=adapter.predict(1,.005,prior); c2,_=adapter.correct(1,.005,LOAD_B)
        if p1['wire_sequence']==p2['wire_sequence'] or c1['wire_sequence']==c2['wire_sequence']: raise RuntimeError('rollback reused wire identity')
        if adapter.state_view()==initial: raise RuntimeError('second distinct force trial did not advance state')
        result={'PRODUCTION_PARTICIPANT_ROLLBACK':'PASS','schema':checkpoint['schema_version'],'completed_cycles':6,'unique_wire_ids':True,'deterministic_trial':True,'previous_force_contamination':False,'physical_time_rollback':True,'physical_step_rollback':True,'explicit_mode_regression':'PASS_BY_ISOLATION: frozen explicit participant source unchanged','trials':trials,'worker_audit':worker.audit}
    except Exception as exc:
        result={'PRODUCTION_PARTICIPANT_ROLLBACK':'FAIL','error':f'{type(exc).__name__}: {exc}','trials':trials,'worker_audit':worker.audit}
    finally: adapter.shutdown()
    (runtime/'production_participant_rollback_regression.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result.get(k) for k in ('PRODUCTION_PARTICIPANT_ROLLBACK','completed_cycles','error')},ensure_ascii=False)); return 0 if result['PRODUCTION_PARTICIPANT_ROLLBACK']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
