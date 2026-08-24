from __future__ import annotations
import math
from pathlib import Path
import scipy.io as sio
from ..stage4f_c_utf8_checkpoint_reader_repair_v1.utf8 import read_json
from ..multi_slice_mapping.mapping import atomic_write_json
from .probe import ROOT,RESULT
P_EXEC=ROOT/'results/28_stage4f_c_utf8_checkpoint_reader_repair_v1/probe_P_execution.json'; PARENT=ROOT/'cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json'
def total(row,key):return [sum(float(v[a]) for v in row[key]) for a in range(3)]
def impulse(times,forces):return [sum(.5*(forces[i][a]+forces[i+1][a])*(times[i+1]-times[i]) for i in range(len(times)-1)) for a in range(3)]
def endpoint_norm(a,b,scale):return max(math.sqrt(sum((float(a[i+j])-float(b[i+j]))**2 for j in range(3))) for i in range(0,len(a),6))/scale
def tension(checkpoint_path,cp):
 path=Path(checkpoint_path).parent/cp['structure']['runner_checkpoint_relative_path'];state=sio.loadmat(path,squeeze_me=True,struct_as_record=False)['state'];v=[float(x) for x in state.output.tension_N.reshape(-1)];return {'minimum_N':min(v),'maximum_N':max(v)}
def run():
 p=read_json(P_EXEC);q=read_json(RESULT/'probe_Q_execution.json');parent=read_json(PARENT);initial=[sum(float(v[a]) for v in parent['previous_slice_forces_N']) for a in range(3)];times0=[1.5075]
 result={'schema':'stage4f-c-p-q-comparison/1.0','common_ticks':[1510000000,1512500000,1515000000,1517500000,1520000000,1522500000]}
 scale=500*1*50*.015
 for kind in ('raw_slice_forces_N','applied_slice_forces_N'):
  pi=impulse(times0+[x['time_s'] for x in p['steps']],[initial]+[total(x,kind) for x in p['steps']]);qi=impulse(times0+[x['time_s'] for x in q['steps']],[initial]+[total(x,kind) for x in q['steps']]);result[kind]={'P_impulse_Ns':pi,'Q_impulse_Ns':qi,'absolute_difference_Ns':[abs(pi[i]-qi[i]) for i in range(3)],'normalized_difference':[abs(pi[i]-qi[i])/scale for i in range(3)]}
 rows=[];first=None
 for ps,qs in zip(p['steps'],q['steps'][1::2]):
  comps={}
  for kind in ('raw_slice_forces_N','applied_slice_forces_N'):
   a=total(ps,kind);b=total(qs,kind);comps[kind]=[abs(a[i]-b[i])/max(25000.,abs(a[i]),abs(b[i])) for i in range(3)]
  row={'tick':ps['time_tick'],'P_step':ps['step'],'Q_step':qs['step'],'normalized_force_point_difference':comps};rows.append(row)
  if first is None and max(comps['raw_slice_forces_N'][:2]+comps['applied_slice_forces_N'][:2])>.05:first=row
 pcp=read_json(p['steps'][-1]['checkpoint']);qcp=read_json(q['steps'][-1]['checkpoint']);pt=tension(p['steps'][-1]['checkpoint'],pcp);qt=tension(q['steps'][-1]['checkpoint'],qcp)
 result.update(common_rows=rows,first_divergence=first,endpoint={'q_max_abs':max(abs(float(a)-float(b)) for a,b in zip(pcp['structure']['q'],qcp['structure']['q'])),'qdot_max_abs':max(abs(float(a)-float(b)) for a,b in zip(pcp['structure']['qdot'],qcp['structure']['qdot'])),'qddot_max_abs':max(abs(float(a)-float(b)) for a,b in zip(pcp['structure']['qddot'],qcp['structure']['qddot'])),'position_difference_over_D':endpoint_norm(pcp['structure']['q'],qcp['structure']['q'],1.),'velocity_difference_over_U':endpoint_norm(pcp['structure']['qdot'],qcp['structure']['qdot'],1.),'P_tension_N':pt,'Q_tension_N':qt,'tension_relative_difference':{k:abs(pt[k]-qt[k])/max(1.,abs(pt[k]),abs(qt[k])) for k in pt}})
 diffs=result['raw_slice_forces_N']['normalized_difference'][:2]+result['applied_slice_forces_N']['normalized_difference'][:2];result['passed']=max(diffs)<=.05 and result['endpoint']['position_difference_over_D']<=.005 and result['endpoint']['velocity_difference_over_U']<=.01 and max(result['endpoint']['tension_relative_difference'].values())<=.05;atomic_write_json(RESULT/'P_Q_comparison.json',result);return result
