"""Read-only, common-physical-time comparison for the one permitted dt-half run."""
from __future__ import annotations
import json,math,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).parent; sys.path.insert(0,str(ROOT/'src'))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.slice_independence_audit_v1.audit import parse_forces
from coupling.multi_slice_mapping.mapping import SliceDefinition,SliceManifest,build_H_for_manifest,motion_from_ancf_state
from quality_v4 import evaluate_quality_v4
RUN='parallel_explicit_fsi_timestep_stability_v1_run_001'; R=ROOT/'runtime'/RUN; O=ROOT/'results'/RUN; B=ROOT/'runtime/preconditioned_coupled_0p1s_smoke_v1_run_003'; V4=HERE/'openfoam_quality_contract_v4.json'; FREF=1350.198335726*50/3
def rows(path): return [json.loads(x) for x in path.read_text(encoding='utf8').splitlines()]
def force(case):
 p=list(case.glob('postProcessing/cylinderForces/*/forces.dat')); return parse_forces(p[0]) if len(p)==1 else {}
def near(d,t): return next((v for k,v in d.items() if abs(float(k)-t)<1e-9),None)
def first(items,pred): return next((x['tau_s'] for x in items if pred(x)),None)
def corrected(records,contract):
 items=contract['slices']['items']; length=float(contract['ANCF']['length_m']); elements=int(contract['ANCF']['elements']); defs=tuple(SliceDefinition(int(x['slice_id']),float(x['s_ref_m']),length/len(items),float(x['unit_span_m'])) for x in items); manifest=SliceManifest('0.2.1',str(contract['case_id']),length,length,defs); H=build_H_for_manifest(manifest,tuple(length*i/elements for i in range(elements+1)))
 return [[motion_from_ancf_state(manifest,sid,H[sid],r['ancf_state']['q'],r['ancf_state']['qdot'],r['ancf_state']['qddot'],step=int(r['global_step']),time_s=float(r['time_s']),reference_position_m=(0.,0.,defs[sid].s_ref_m)).to_dict() for sid in range(3)] for r in records]
def seq(records,corr,sid): return [{'tau_s':float(r['time_s']),'Fx_N':float(r['loads'][sid]['force_x_N']),'ux_m':float(r['motion'][sid]['ux_m']),'vx_mps':float(r['motion'][sid]['vx_mps']),'vc_mps':float(corr[index][sid]['vx_mps'])} for index,r in enumerate(records)]
def work(series,dt): return sum(x['Fx_N']*(x['vx_mps']+x['vc_mps'])/2*dt for x in series)
def signs(values):
 s=[1 if v>0 else -1 for v in values if v!=0]; return sum(a!=b for a,b in zip(s,s[1:]))
def mesh_summary():
 out={}
 for sid in range(3):
  p=ROOT/'results'/f'{RUN}_slice{sid:04d}_mesh_sweep.stdout'
  if not p.is_file(): p=ROOT/'results'/f'{RUN}_slice{sid}_mesh_sweep.stdout'
  if not p.is_file(): out[str(sid)]={'status':'not_available'}; continue
  text=p.read_text(encoding='utf8',errors='replace'); blocks=re.split(r'Time = ',text)[1:]; first_bad=None
  for b in blocks:
   time=b.split('s',1)[0].strip()
   if 'Zero or negative cell volume' in b or 'Failed ' in b: first_bad=time; break
  match=re.search(r'Minimum negative volume:\s*([-+0-9.eE]+), Number of negative volume cells:\s*(\d+)',text)
  out[str(sid)]={'first_failed_mesh_time_s':None if first_bad is None else float(first_bad),'negative_volume_count':None if not match else int(match.group(2)),'minimum_negative_volume':None if not match else float(match.group(1)),'sweep_return_mesh_ok_until_failure':first_bad is None}
 return out
def main():
 test=rows(R/'records.jsonl'); base=rows(B/'records.jsonl'); tcorr=corrected(test,json.loads((HERE/'parallel_explicit_fsi_timestep_stability_v1_contract.json').read_text(encoding='utf8'))); bcorr=corrected(base,json.loads((ROOT/'tools/preconditioned_coupled_0p1s_smoke_v1/preconditioned_coupled_0p1s_smoke_v1_contract.json').read_text(encoding='utf8'))); tf=[force(R/'cases'/f'slice_{i:04d}') for i in range(3)]; bf=[force(B/'cases'/f'slice_{i:04d}') for i in range(3)]
 q={str(i):evaluate_quality_v4(audit_log(R/'logs'/f'fluid_{i:04d}.stdout',R/'cases'/f'slice_{i:04d}'/'system/fvSolution'),json.loads(V4.read_text(encoding='utf8'))) for i in range(3)}
 common=[]
 for tick in range(1,14):
  tau=.005*tick; entry={'tau_s':tau,'slices':[]}
  for sid in range(3):
   br=base[tick-1]; tr=next((r for r in test if abs(float(r['time_s'])-tau)<1e-12),None); rawb=near(bf[sid],.1+tau); rawt=near(tf[sid],.1+tau)
   entry['slices'].append({'Fx_baseline_raw_N':None if rawb is None else rawb['total_N'][0],'Fx_dt_half_raw_N':None if rawt is None else rawt['total_N'][0],'vx_baseline_mps':float(br['motion'][sid]['vx_mps']),'vx_dt_half_mps':None if tr is None else float(tr['motion'][sid]['vx_mps']),'ux_baseline_m':float(br['motion'][sid]['ux_m']),'ux_dt_half_m':None if tr is None else float(tr['motion'][sid]['ux_m'])})
  common.append(entry)
 ts=[seq(test,tcorr,i) for i in range(3)]; bs=[seq(base,bcorr,i) for i in range(3)]
 rawmax=[max((abs(float(v['total_N'][0])) for v in tf[i].values()),default=math.inf) for i in range(3)]; integmax=[max((abs(x['Fx_N']) for x in ts[i]),default=math.inf) for i in range(3)]; vxmax=[max((abs(x['vx_mps']) for x in ts[i]),default=math.inf) for i in range(3)]; uxmax=[max((abs(x['ux_m']) for x in ts[i]),default=math.inf) for i in range(3)]
 brawmax=[max((abs(float(v['total_N'][0])) for v in bf[i].values()),default=math.inf) for i in range(3)]; bvx=[max(abs(x['vx_mps']) for x in bs[i]) for i in range(3)]; bux=[max(abs(x['ux_m']) for x in bs[i]) for i in range(3)]
 metric={'R_F':[rawmax[i]/brawmax[i] for i in range(3)],'R_v':[vxmax[i]/bvx[i] for i in range(3)],'R_u':[uxmax[i]/bux[i] for i in range(3)],'R_Co':[q[str(i)]['max_courant']/[1.6266188341,.808266742574,1.63295213989][i] for i in range(3)]}
 thresholds=[]
 for i in range(3): thresholds.append({'slice_id':i,'test_time_to_5x_drag_s':first(ts[i],lambda x:abs(x['Fx_N'])>=5*FREF),'test_time_to_10x_drag_s':first(ts[i],lambda x:abs(x['Fx_N'])>=10*FREF),'test_time_to_100x_drag_s':first(ts[i],lambda x:abs(x['Fx_N'])>=100*FREF),'test_time_to_abs_vx_gt_1_s':first(ts[i],lambda x:abs(x['vx_mps'])>1),'baseline_time_to_5x_drag_s':first(bs[i],lambda x:abs(x['Fx_N'])>=5*FREF),'baseline_time_to_10x_drag_s':first(bs[i],lambda x:abs(x['Fx_N'])>=10*FREF),'baseline_time_to_100x_drag_s':first(bs[i],lambda x:abs(x['Fx_N'])>=100*FREF),'baseline_time_to_abs_vx_gt_1_s':first(bs[i],lambda x:abs(x['vx_mps'])>1)})
 aux={str(i):{'max_iterations':max((x['linear_iterations'] for x in q[str(i)]['classifications'] if x['group']=='mesh_motion_auxiliary'),default=None),'max_final_residual':max((x['final_residual'] for x in q[str(i)]['classifications'] if x['group']=='mesh_motion_auxiliary'),default=None),'status':q[str(i)]['auxiliary_efficiency_status']} for i in range(3)}
 result={'run_id':RUN,'completed_windows':len(test),'expected_windows':40,'run_status':'FAIL_CONTAINMENT_AND_FPE','quality_v4':q,'max_abs_raw_Fx_N':rawmax,'max_abs_integrated_Fx_N':integmax,'max_abs_vx_mps':vxmax,'max_abs_ux_m':uxmax,'max_fluid_Courant':[q[str(i)]['max_courant'] for i in range(3)],'ratios':metric,'threshold_times':thresholds,'streamwise_work_J':{'dt_half':[work(x,.0025) for x in ts],'baseline':[work(x,.005) for x in bs]},'Fx_sign_reversals':{'dt_half':[signs([x['Fx_N'] for x in s]) for s in ts],'baseline':[signs([x['Fx_N'] for x in s]) for s in bs]},'mesh_auxiliary':aux,'mesh_sweep':mesh_summary(),'common_physical_time_comparison':common,'classification':'WORSE_AT_SMALLER_DT','explicit_time_layer_evidence':'not_supported: halving dt did not stabilize the closed loop; it escalated and failed before 0.100 s.','added_mass_claim':'not_established','first_containment_breach':{'raw_force':min((x['tau_s'] for s in ts for x in s if abs(x['Fx_N'])>2e6),default=None),'vx':min((x['tau_s'] for s in ts for x in s if abs(x['vx_mps'])>20),default=None),'ux':min((x['tau_s'] for s in ts for x in s if abs(x['ux_m'])>.1),default=None)}}
 O.mkdir(parents=True,exist_ok=True); (O/'dt_half_analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8'); print(json.dumps({k:result[k] for k in ('completed_windows','max_abs_raw_Fx_N','max_abs_vx_mps','max_abs_ux_m','ratios','classification','first_containment_breach')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
