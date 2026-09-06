"""The only real CFD execution in this task: one implicit 0.005 s window."""
from __future__ import annotations
import importlib.util, json, math, re, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).parent; sys.path.insert(0,str(ROOT/'src'))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.slice_independence_audit_v1.audit import parse_forces, sha256
from coupling.ancf_newton_evidence_v1 import validate_records
RUN='implicit_one_window_v1_run_001'; RUNTIME=ROOT/'runtime'/RUN; RESULTS=ROOT/'results'/RUN
CONTRACT=HERE/'one_window_implicit_qualification_contract_v1.json'; V4=ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/openfoam_quality_contract_v4.json'
PART=HERE/'implicit_structure_participant.py'; WORKER=ROOT/'runtime/parallel_implicit_coupling_readiness_and_0p05s_diagnostic_v1/cpp_worker_build/cfd_ancf_ancf_kernel_worker'
OUT=ROOT/'docs/checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1/CHECKPOINT_AWARE_STRUCTURE_PARTICIPANT_AND_ONE_WINDOW_IMPLICIT_QUALIFICATION_V1_REPORT.md'
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); assert s and s.loader; s.loader.exec_module(m); return m
evaluate_quality_v4=load(ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/quality_v4.py','one_window_quality_v4').evaluate_quality_v4
def write(path,value): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def implicit_xml(base,sid):
 original=base.xml(sid); replacement=(f'<coupling-scheme:parallel-implicit><participants first="Structure_{sid:04d}" second="Fluid_{sid:04d}"/>'
 '<max-time value="0.005"/><time-window-size value="0.005"/><min-iterations value="2"/><max-iterations value="8"/>'
 '<absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="1e-8" rel-limit="1e-5"/>'
 '<absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="1e-3" rel-limit="1e-5"/>'
 f'<exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{sid:04d}" to="Fluid_{sid:04d}"/>'
 f'<exchange data="Force" mesh="Structure-Mesh" from="Fluid_{sid:04d}" to="Structure_{sid:04d}"/>'
 '</coupling-scheme:parallel-implicit>')
 return re.sub(r'<coupling-scheme:parallel-explicit>.*?</coupling-scheme:parallel-explicit>',replacement,original,flags=re.S)
def build_contract(c):
 c.update({'schema_version':'one-window-implicit-qualification-v1','run_id':RUN,'case_id':'implicit_one_window_v1_case_001','duration_s':.005,'number_of_steps':1,'openfoam_physical_time_offset_s':.1,'coupling_scheme':'parallel-implicit','implicit_convergence':{'min_iterations':2,'max_iterations':8,'acceleration':'none','measures':[{'data':'Displacement','mesh':'Structure-Mesh','abs_limit':1e-8,'rel_limit':1e-5},{'data':'Force','mesh':'Structure-Mesh','abs_limit':1e-3,'rel_limit':1e-5}]},'quality_contract_v4':{'source':str(V4),'sha256':sha256(V4),'frozen_before_run':True},'qualification_scope':'exactly one physical window; stop after commit'})
 return c
def main():
 p=load(ROOT/'tools/preconditioned_coupled_0p1s_smoke_v1/run_smoke.py','one_window_preconditioned')
 original_contract=p.contract
 p.RUN=RUN; p.RUNTIME=RUNTIME; p.RESULTS=RESULTS; p.HERE=HERE; p.STEPS=1; p.DT=.005; p.QUALITY=V4; p.contract=lambda:build_contract(original_contract())
 p.cfg_xml=implicit_xml
 p.control=lambda base: base.CONTROL.replace('startFrom startTime; startTime 0; stopAt endTime; endTime 1;','startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.105;')
 base,cases,contract=p.prepare(); base.PARTICIPANT_SCRIPT=PART; base.WORKER=WORKER
 rc=base.launch(cases)
 summary=json.loads((RUNTIME/'structure_summary.json').read_text()) if (RUNTIME/'structure_summary.json').is_file() else {}
 rows=[json.loads(x) for x in (RUNTIME/'records.jsonl').read_text().splitlines()] if (RUNTIME/'records.jsonl').is_file() else []
 iters=[json.loads(x) for x in (RUNTIME/'implicit_iterations.jsonl').read_text().splitlines()] if (RUNTIME/'implicit_iterations.jsonl').is_file() else []
 quality={}; forces=[]
 for sid,case in enumerate(cases):
  quality[str(sid)]=evaluate_quality_v4(audit_log(RUNTIME/'logs'/f'fluid_{sid:04d}.stdout',case/'system/fvSolution'),json.loads(V4.read_text()))
  fs=list(case.glob('postProcessing/cylinderForces/*/forces.dat')); forces.append(parse_forces(fs[0]) if len(fs)==1 else {})
 final_forces=[]
 for sid,data in enumerate(forces):
  value=next((v for t,v in data.items() if abs(float(t)-.105)<1e-9),None); final_forces.append(None if value is None else {'pressure_Fx_N':value['pressure_N'][0],'viscous_Fx_N':value['viscous_N'][0],'total_Fx_N':value['total_N'][0]})
 newton=[json.loads(x) for x in (RUNTIME/'newton_evidence.jsonl').read_text().splitlines()] if (RUNTIME/'newton_evidence.jsonl').is_file() else []
 try: newton_ok=validate_records(newton,expected_steps=1).get('status')=='pass'
 except Exception: newton_ok=False
 v2=[x for x in iters if x.get('event')=='post_cpp_correction']; v2ok=bool(v2) and all(x['generalized_force_metric_v2']['GENERALIZED_FORCE_MAPPING_V2']=='PASS' for x in v2)
 writes=sum(x.get('event')=='checkpoint_write' for x in iters); restores=sum(x.get('event')=='checkpoint_restore' for x in iters); wires=[x.get('wire_sequence') for x in v2]; restored=[x for x in iters if x.get('event')=='checkpoint_restore']
 rollback_ok=bool(restored) and all(x.get('checkpoint_state_sha256')==x.get('post_restore_state_sha256') for x in restored)
 firstok=all(x is not None and abs(x['total_Fx_N'])<=5000 for x in final_forces)
 checks={'launch_return':rc==0,'one_committed_window':len(rows)==1 and summary.get('committed_steps')==1,'min_two_iterations':summary.get('coupling_iterations',0)>=2,'max_eight_iterations':summary.get('coupling_iterations',99)<=8,'checkpoint_write':writes>=1,'checkpoint_restore':restores>=1,'structure_rollback':rollback_ok,'unique_wire_ids':len(wires)==len(set(wires)) and len(wires)>=2,'quality_v4':all(q['status']=='pass' for q in quality.values()),'generalized_force_v2':v2ok,'newton':newton_ok,'first_force_guard':firstok,'final_of_time':len(rows)==1,'no_fpe':rc==0 and summary.get('status')=='completed'}
 result={'ONE_WINDOW_IMPLICIT_QUALIFICATION':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'return_code':rc,'structure_summary':summary,'iteration_evidence':iters,'quality_v4':quality,'final_raw_force':final_forces,'committed_rows':rows,'openfoam_dynamic_mesh_rollback':'PENDING_LOG_EVIDENCE' if restores else 'NOT_OBSERVED'}
 write(RESULTS/'one_window_gate.json',result); print(json.dumps({'gate':result['ONE_WINDOW_IMPLICIT_QUALIFICATION'],'iterations':summary.get('coupling_iterations'),'windows':len(rows)},ensure_ascii=False)); return 0 if result['ONE_WINDOW_IMPLICIT_QUALIFICATION']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
