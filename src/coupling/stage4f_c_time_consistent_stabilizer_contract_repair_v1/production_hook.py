from __future__ import annotations
import json,math
from decimal import Decimal
from pathlib import Path
from ..stage4f_c_stabilized_production_hook_v1.hook import FrozenLoadStabilizer,StabilizationGateError,RAW_CD_LIMIT,APPLIED_CD_LIMIT
from ..multi_slice_mapping.mapping import LoadRecord
from .contract import ROOT
CONTRACT=ROOT/'results/25_stage4f_c_time_consistent_stabilizer_contract_repair_v1/canonical_time_consistent_contract.json'
class TimeConsistentLoadStabilizer(FrozenLoadStabilizer):
 checkpoint_schema='0.2.1+stabilizer.time-consistent.1'; requires_raw_snapshot_manifest=True
 def __init__(self,**kw):
  super().__init__(**kw); c=json.loads(CONTRACT.read_text(encoding='utf8')); encoded=dict(c); expected=encoded.pop('canonical_sha256'); import hashlib; actual=hashlib.sha256(json.dumps(encoded,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  if actual!=expected:raise StabilizationGateError('canonical contract hash mismatch')
  self.contract_hash=expected;self.tau=float(Decimal(c['source']['tau_canonical_decimal']))
 def initialize_from_legacy(self,restored,*,run_id,case_id):
  s=super().initialize_from_legacy(restored);s.update(schema=self.checkpoint_schema,contract_sha256=self.contract_hash,tau_decimal=json.loads(CONTRACT.read_text(encoding='utf-8'))['source']['tau_canonical_decimal'],run_id=run_id,case_id=case_id);return s
 def apply(self,**kw):
  st=kw['previous_state'];required={'schema','contract_sha256','tau_decimal','run_id','case_id','last_time_tick','previous_applied_force_N'}
  if not required.issubset(st) or st['schema']!=self.checkpoint_schema or st['contract_sha256']!=self.contract_hash or st['run_id']!=kw['run_id'] or st['case_id']!=kw['case_id']:raise StabilizationGateError('time-consistent state identity mismatch')
  dt=(int(kw['time_tick'])-int(st['last_time_tick']))*1e-9
  if dt<=0 or not math.isfinite(dt):raise StabilizationGateError('invalid physical dt')
  alpha=-math.expm1(-dt/self.tau);raws=sorted(kw['raw_loads'],key=lambda x:x.slice_id);old=st['previous_applied_force_N'];applied=[];matrix=[];keys={(kw['case_id'],kw['run_id'],kw['step'],kw['time_tick'],r.slice_id) for r in raws}
  if keys & self._seen or {r.slice_id for r in raws}!=set(self.scales):raise StabilizationGateError('duplicate/partial raw transaction')
  for i,r in enumerate(raws):
   force=tuple(map(float,r.force_N));prev=tuple(map(float,old[i]));
   if any(not math.isfinite(v) for v in force+prev) or abs(force[0]/self.scales[r.slice_id])>RAW_CD_LIMIT:raise StabilizationGateError('force gate failed')
   val=tuple((1-alpha)*p+alpha*f for p,f in zip(prev,force));matrix.append(list(val))
   if abs(val[0]/self.scales[r.slice_id])>APPLIED_CD_LIMIT:raise StabilizationGateError('applied gate failed')
   spec=type('S',(),{'slice_id':r.slice_id,'s_ref_m':r.s_ref_m,'slice_length_m':r.slice_length_m,'unit_span_m':r.unit_span_m})();applied.append(LoadRecord.from_conversion(case_id=r.case_id,step=r.step,time_s=r.time_s,slice_definition=spec,unit_span_m=r.unit_span_m,openfoam_force_N=tuple(v*r.unit_span_m/r.slice_length_m for v in val),cfd_time_step_s=r.cfd_time_step_s))
  self._pending_keys=keys;s=dict(st);s.update(previous_applied_force_N=matrix,last_step=kw['step'],last_time_tick=kw['time_tick'],alpha_dt=alpha,elapsed_dt_s=dt);return {'applied_loads':applied,'state':s}
