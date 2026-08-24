from __future__ import annotations
import hashlib, json, math
from typing import Mapping
from ..stage4f_c_stabilized_production_hook_v1.hook import FrozenLoadStabilizer, StabilizationGateError, ALGORITHM

TAU_S=-0.0025/math.log(0.9)
STATE_SCHEMA="0.2.1+stabilizer.time-consistent.1"
TC_ALGORITHM="first_order_load_relaxation_physical_time"

class TimeConsistentLoadStabilizer(FrozenLoadStabilizer):
    checkpoint_schema=STATE_SCHEMA
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config_hash=hashlib.sha256(json.dumps({"algorithm":TC_ALGORITHM,"tau_s":TAU_S,"scales":self.scales,"tick_hz":10**9},sort_keys=True).encode()).hexdigest()
    def initialize_from_legacy(self, restored:Mapping[str,object], *, run_id:str, case_id:str):
        state=super().initialize_from_legacy(restored)
        state.update(schema=STATE_SCHEMA,algorithm=TC_ALGORITHM,version="1.0.0",tau_s=TAU_S,run_id=run_id,case_id=case_id,last_raw_identity=None,last_applied_identity=None)
        return state
    def _validate_state(self,state,run_id,case_id):
        required={"schema","algorithm","tau_s","config_sha256","run_id","case_id","last_time_tick","previous_applied_force_N"}
        if not required.issubset(state): raise StabilizationGateError("time-consistent state incomplete")
        if state["schema"]!=STATE_SCHEMA or state["algorithm"]!=TC_ALGORITHM: raise StabilizationGateError("mixed old/new stabilizer state")
        if float(state["tau_s"])!=TAU_S or state["config_sha256"]!=self.config_hash: raise StabilizationGateError("wrong tau/config")
        if state["run_id"]!=run_id or state["case_id"]!=case_id: raise StabilizationGateError("cross run/case state")
    def apply(self,**kwargs):
        state=kwargs["previous_state"]; self._validate_state(state,kwargs["run_id"],kwargs["case_id"])
        tick=int(kwargs["time_tick"]); last=int(state["last_time_tick"]); dt=(tick-last)*1e-9
        if dt<=0 or not math.isfinite(dt): raise StabilizationGateError("nonpositive/nonfinite physical dt")
        alpha=-math.expm1(-dt/TAU_S)
        # Reuse all identity, force, Cd and conversion gates, substituting the exact physical-time alpha locally.
        import coupling.stage4f_c_stabilized_production_hook_v1.hook as legacy
        old_alpha=legacy.ALPHA
        try:
            legacy.ALPHA=alpha; outcome=super().apply(**kwargs)
        finally: legacy.ALPHA=old_alpha
        s=dict(outcome["state"]); ident={"run_id":kwargs["run_id"],"case_id":kwargs["case_id"],"step":kwargs["step"],"time_tick":tick}
        s.update(schema=STATE_SCHEMA,algorithm=TC_ALGORITHM,version="1.0.0",tau_s=TAU_S,config_sha256=self.config_hash,run_id=kwargs["run_id"],case_id=kwargs["case_id"],last_raw_identity=ident,last_applied_identity=ident,alpha_dt=alpha,elapsed_dt_s=dt)
        outcome=dict(outcome); outcome["state"]=s; return outcome
