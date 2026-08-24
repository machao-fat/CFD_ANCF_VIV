from __future__ import annotations
import hashlib
import json
import math
from typing import Any, Mapping, Sequence
from ..multi_slice_mapping.mapping import LoadRecord

ALPHA=0.1
RAW_CD_LIMIT=10.0
APPLIED_CD_LIMIT=10.0
VELOCITY_LIMIT=0.01
ALGORITHM="first_order_load_under_relaxation"
VERSION="1.0.0"

class StabilizationGateError(RuntimeError): pass

class FrozenLoadStabilizer:
    def __init__(self, *, slice_force_scales_N: Mapping[int,float], velocity_auditor=None):
        self.scales={int(k):float(v) for k,v in slice_force_scales_N.items()}
        if any(not math.isfinite(v) or v<=0 for v in self.scales.values()): raise ValueError("invalid Cd force scale")
        self._committed: dict[str,Any]={}
        self._seen:set[tuple[str,str,int,int,int]]=set()
        self._pending_keys:set[tuple[str,str,int,int,int]]=set()
        self.velocity_auditor=velocity_auditor
        self.config_hash=hashlib.sha256(json.dumps({"alpha":ALPHA,"algorithm":ALGORITHM,"scales":self.scales},sort_keys=True).encode()).hexdigest()
    def initialize_from_legacy(self, restored: Mapping[str,object]) -> Mapping[str,object]:
        return {"algorithm":ALGORITHM,"version":VERSION,"config_sha256":self.config_hash,
                "previous_applied_force_N":restored["previous_slice_forces_N"],"last_step":int(restored["step"]),
                "last_time_tick":int(round(float(restored["time_s"])*1e9)),"iteration":1,"residual":0.0}
    def apply(self, *, step:int,time_s:float,time_tick:int,case_id:str,run_id:str,raw_loads:Sequence[LoadRecord],previous_state:Mapping[str,object])->Mapping[str,object]:
        if abs(time_s-time_tick*1e-9)>5e-13: raise StabilizationGateError("integer tick mismatch")
        if set(r.slice_id for r in raw_loads)!=set(self.scales): raise StabilizationGateError("partial or wrong slice transaction")
        keys={(case_id,run_id,step,time_tick,r.slice_id) for r in raw_loads}
        if keys & self._seen: raise StabilizationGateError("duplicate raw force consumption")
        old=previous_state.get("previous_applied_force_N")
        if not isinstance(old,list) or len(old)!=len(raw_loads): raise StabilizationGateError("stabilizer history is incomplete")
        applied=[]; applied_matrix=[]; max_residual=0.0
        for index,raw in enumerate(sorted(raw_loads,key=lambda r:r.slice_id)):
            force=tuple(float(v) for v in raw.force_N)
            if any(not math.isfinite(v) for v in force): raise StabilizationGateError("raw force is NaN/Inf")
            raw_cd=force[0]/self.scales[raw.slice_id]
            if abs(raw_cd)>RAW_CD_LIMIT: raise StabilizationGateError(f"raw Cd hard gate failed at slice {raw.slice_id}")
            previous=tuple(float(v) for v in old[index])
            value=tuple((1-ALPHA)*p+ALPHA*f for p,f in zip(previous,force))
            if abs(value[0]/self.scales[raw.slice_id])>APPLIED_CD_LIMIT: raise StabilizationGateError(f"applied Cd hard gate failed at slice {raw.slice_id}")
            residual=max(abs(a-p)/max(abs(f),500.0) for a,p,f in zip(value,previous,force))
            max_residual=max(max_residual,residual); applied_matrix.append(list(value))
            openfoam=tuple(v*raw.unit_span_m/raw.slice_length_m for v in value)
            spec=type("AppliedSlice",(),{"slice_id":raw.slice_id,"s_ref_m":raw.s_ref_m,
                "slice_length_m":raw.slice_length_m,"unit_span_m":raw.unit_span_m})()
            applied.append(LoadRecord.from_conversion(case_id=raw.case_id,step=raw.step,time_s=raw.time_s,
                slice_definition=spec,unit_span_m=raw.unit_span_m,openfoam_force_N=openfoam,
                cfd_time_step_s=raw.cfd_time_step_s))
        self._pending_keys=keys
        state={"algorithm":ALGORITHM,"version":VERSION,"config_sha256":self.config_hash,"previous_applied_force_N":applied_matrix,
               "last_step":step,"last_time_tick":time_tick,"iteration":1,"residual":max_residual}
        return {"applied_loads":applied,"state":state}
    def validate_correction(self, correction:Mapping[str,object], *, predicted_motion=None, staged_state=None)->None:
        audit=correction.get("audit",{})
        if isinstance(audit,Mapping):
            value=audit.get("max_committed_predictor_velocity_gap_over_U",audit.get("velocity_consistency_error"))
            if value is not None and float(value)>VELOCITY_LIMIT: raise StabilizationGateError("velocity consistency hard gate failed")
        if self.velocity_auditor is not None:
            value=float(self.velocity_auditor(predicted_motion,staged_state))
            if not math.isfinite(value) or value>VELOCITY_LIMIT: raise StabilizationGateError("velocity consistency hard gate failed")
    def commit(self,state:Mapping[str,object])->None:
        self._committed=dict(state); self._seen.update(self._pending_keys); self._pending_keys=set()
    def rollback(self)->None: self._pending_keys=set()
