"""Read-only audit of the completed implicit one-window runtime."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'src'))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.slice_independence_audit_v1.audit import parse_forces
from coupling.moving_mesh_openfoam10_case_contract_v1 import preflight
import importlib.util
def load(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);assert s and s.loader;s.loader.exec_module(m);return m
v4=load(ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/quality_v4.py','audit_v4').evaluate_quality_v4
RUN='implicit_one_window_requal_v1_run_001'; RUNTIME=ROOT/'runtime'/RUN; RESULTS=ROOT/'results'/RUN
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def main():
 summary=json.loads((RUNTIME/'structure_summary.json').read_text(encoding='utf8')); rows=[json.loads(x) for x in (RUNTIME/'records.jsonl').read_text(encoding='utf8').splitlines()]; iters=[json.loads(x) for x in (RUNTIME/'implicit_iterations.jsonl').read_text(encoding='utf8').splitlines()]; qcontract=json.loads((ROOT/'tools/parallel_explicit_fsi_timestep_stability_diagnostic_v1/openfoam_quality_contract_v4.json').read_text())
 quality={}; cases=[]; forces=[]; rollback_logs=[]; final_hash={}
 for sid in range(3):
  case=RUNTIME/'cases'/f'slice_{sid:04d}'; cases.append(case)
  source_log=RUNTIME/'logs'/f'fluid_{sid:04d}.stdout'; text=source_log.read_text(encoding='utf8',errors='replace'); marker='Time = 0.105s'
  # A parallel-implicit retry deliberately repeats the same physical time.
  # Quality V4 applies to the final committed trial only, not to a merged
  # duplicate-time log that its explicit-time parser correctly rejects.
  pieces=text.split(marker)
  if len(pieces)!=3: raise RuntimeError('expected exactly two implicit trial time markers')
  # OpenFOAM writes the Courant line immediately before Time. Preserve the
  # last one associated with the final retry, then retain only its trial.
  prefix=pieces[1]; courant=prefix[prefix.rfind('Courant Number'):]
  final_log=RESULTS/f'fluid_{sid:04d}_final_committed_trial.stdout'; final_log.parent.mkdir(parents=True,exist_ok=True); final_log.write_text(courant+marker+pieces[2],encoding='utf8')
  quality[str(sid)]=v4(audit_log(final_log,case/'system/fvSolution'),qcontract)
  file=next(iter(case.glob('postProcessing/cylinderForces/*/forces.dat'))); data=parse_forces(file); force=next(v for t,v in data.items() if abs(float(t)-.105)<1e-9); forces.append({'slice_id':sid,'pressure_Fx_N':force['pressure_N'][0],'viscous_Fx_N':force['viscous_N'][0],'total_Fx_N':force['total_N'][0]})
  rollback_logs.append(text.count('Time = 0.105s'))
  final_hash[str(sid)]={name:sha(case/'0.105'/name) for name in ('U','p','phi','Uf','meshPhi','pointDisplacement','cellDisplacement','polyMesh/points')}
 v2=[x for x in iters if x.get('event')=='post_cpp_correction']; restored=[x for x in iters if x.get('event')=='checkpoint_restore']; field_observable=False
 checks={'shared_case_contract':all(preflight(c,'0.1')['MOVING_MESH_CASE_PREFLIGHT']=='PASS' for c in cases),'committed_once':len(rows)==1 and summary['committed_steps']==1,'iterations_2_to_8':summary['coupling_iterations']==2,'structure_rollback':bool(restored) and all(x['checkpoint_state_sha256']==x['post_restore_state_sha256'] for x in restored),'wire_unique':len({x['wire_sequence'] for x in v2})==2,'openfoam_rollback_observed':rollback_logs==[2,2,2],'openfoam_field_rollback_verified':field_observable,'dynamic_mesh_rollback_verified':field_observable,'quality_v4':all(x['status']=='pass' for x in quality.values()),'generalized_force_v2':len(v2)==2 and all(x['generalized_force_metric_v2']['GENERALIZED_FORCE_MAPPING_V2']=='PASS' for x in v2),'no_fpe':summary['status']=='completed'}
 result={'ONE_WINDOW_IMPLICIT_REQUALIFICATION':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'summary':summary,'quality_v4':quality,'final_raw_force':forces,'rollback_time_105_log_count':rollback_logs,'final_field_hashes':final_hash,'reason':'adapter checkpoint/rollback occurred at same physical time, but deployed adapter exposes no checkpoint-time U/p/phi/Uf/meshPhi/mesh-coordinate snapshots; direct field and dynamic-mesh rollback identities are therefore not evaluable.'}
 RESULTS.mkdir(parents=True,exist_ok=True); (RESULTS/'one_window_requalification_gate.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps({'gate':result['ONE_WINDOW_IMPLICIT_REQUALIFICATION'],'checks':checks},ensure_ascii=False)); return 0 if result['ONE_WINDOW_IMPLICIT_REQUALIFICATION']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
