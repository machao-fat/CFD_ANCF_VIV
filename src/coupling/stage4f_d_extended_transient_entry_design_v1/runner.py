from __future__ import annotations
import hashlib, json, math
from pathlib import Path

DT=0.00125; T0=1.5075; BASELINE_END=1.5575; TAU=0.023728053952574758
PARENT_SHA="5db86ae104015d51a8268862a1551579d96d0ddc7f55536371efc0334e"

def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def build_design(out: str|Path):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    conv=0.01/1.0; f1=2.0; period=1/f1
    physical={"D_m":0.01,"U_m_per_s":1.0,"rho_kg_per_m3":1000.0,"mu_Pa_s":0.1,
              "Re":100.0,"convective_time_s":conv,"first_mode_frequency_Hz":f1,
              "first_mode_period_s":period,"prior_St_range":[0.1,0.2],
              "prior_shedding_period_range_s":[conv/0.2,conv/0.1],
              "provenance":{"Re":"contract-derived","frequency":"frozen structural input",
              "St":"literature prior only; not measured"}}
    windows=[]
    for name,extra in [("E1",.05),("E2",.10),("E3",.20)]:
        steps=round(extra/DT); windows.append({"id":name,"additional_window_s":extra,"global_steps":steps,
          "convective_times":extra/conv,"first_mode_periods":extra/period,
          "prior_shedding_periods_range":[extra/physical["prior_shedding_period_range_s"][1],extra/physical["prior_shedding_period_range_s"][0]],
          "frequency_evaluable":False,"technical_transient":True})
    contracts={
      "recommended_pilot_contract":{"status":"designed_pending_authorization","dt_s":DT,"source_checkpoint":{"id":"checkpoint_step00000039_accepted_C","sha256":"read_from_stage40_immutable_evidence","parent_sha256":PARENT_SHA},"start_time_s":BASELINE_END,"end_time_s":BASELINE_END+0.05,"global_steps":40,"block_length_steps":10,"blocks":4,"restart_count":3,"slices":3,"tau_s":TAU,"field_write_interval_steps":10,"checkpoint_interval_steps":10,"max_wall_clock_s":4*3600,"max_disk_gb":20},
      "statistical_diagnostic_contract":{"discard_rule":"none; retain early transient","minimum_cycles":5,"minimum_samples":256,"frequency_amplitude_floor":"not established; below floor => frequency_not_evaluable","methods":["FFT","zero_crossing"],"agreement_relative_tolerance":0.05,"frequency_not_evaluable_if":"minimum cycles, samples, or amplitude floor unmet"},
      "hard_stop_conditions":{"cfl_ge":0.8,"raw_cd_abs_gt":10,"velocity_consistency_gt":0.01,"virtual_work_gt":1e-12,"force_conversion_gt":1e-10,"nan_inf_fatal":True,"missing_slice_or_checkpoint":True,"owned_residual_gt":0,"wall_clock_budget_exceeded":True,"disk_budget_exceeded":True},
      "claim_boundary":{"strict_asymptotic_convergence":"not_completed","gci":"not_completed","vortex_shedding_statistics":"not_completed","stable_viv_response":"not_completed","five_slice":"do_not_enter","nine_slice":"do_not_enter","long_time_viv":"do_not_enter","stage4e_physical_validation":"not_completed"}}
    data={"stage":"41_stage4f_d_extended_transient_entry_design_v1","parent_checkpoint_sha256":PARENT_SHA,"stage40_gate":"pass","physical_timescale_audit":physical,"current_window_coverage":{"window_s":.05,"convective_times":.05/conv,"first_mode_periods":.05/period,"prior_shedding_periods_range":[.05/physical["prior_shedding_period_range_s"][1],.05/physical["prior_shedding_period_range_s"][0]],"frequency_evaluable":False},"candidate_window_matrix":windows,"runtime_cost_model":{"basis":"Stage40 offline process evidence; conservative planning estimate","seconds_per_global_step":30,"E1_wall_clock_s":40*30,"E2_wall_clock_s":80*30,"E3_wall_clock_s":160*30},"storage_cost_model":{"snapshots_per_step":3,"checkpoint_per_block":1,"estimated_gb":{"E1":2,"E2":4,"E3":8}},"process_budget_model":{"max_concurrent_heavy_processes":1,"processes_per_block":3,"restart_blocks":4},**contracts,"entry_recommendation":{"recommendation":"enter_one_bounded_pilot_pending_user_authorization","rationale":"E1 is finite, blockable, and remains a technical transient; no frequency/VIV claim."}}
    data["contract_hash"]=canonical_hash(data["recommended_pilot_contract"])
    for k,v in data.items():
        (out/(k+".json")).write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding="utf-8")
    return data

if __name__=='__main__':
    import sys; build_design(sys.argv[1] if len(sys.argv)>1 else 'results/41_stage4f_d_extended_transient_entry_design_v1')
