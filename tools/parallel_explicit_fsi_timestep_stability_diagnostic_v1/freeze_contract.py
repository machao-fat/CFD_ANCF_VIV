"""Freeze the single permitted dt-half diagnostic before any CFD starts."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
OUT=HERE/'parallel_explicit_fsi_timestep_stability_v1_contract.json'
PRE=ROOT/'tools/preconditioned_coupled_0p1s_smoke_v1/preconditioned_coupled_0p1s_smoke_v1_contract.json'
V4=HERE/'openfoam_quality_contract_v4.json'
PRECURSOR=ROOT/'results/fixed_cylinder_precursor_initialization_contract_v1_run_002/PRECURSOR_STATE_V1/manifest.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    c=json.loads(PRE.read_text(encoding='utf8'))
    c.update({'schema_version':'parallel-explicit-fsi-timestep-stability-v1','run_id':'parallel_explicit_fsi_timestep_stability_v1_run_001','case_id':'parallel_explicit_fsi_timestep_stability_case_001','git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'dt_s':.0025,'duration_s':.1,'number_of_steps':40,'openfoam_physical_time_offset_s':.1,'time_relation':'t_OF=0.100 s+coupling_time_s','initial_structure_state':'NO_FLOW_EQUILIBRIUM','quality_contract_v4':{'path':str(V4),'sha256':sha(V4),'frozen_before_run':True},'precursor_state':{'manifest_path':str(PRECURSOR),'manifest_sha256':sha(PRECURSOR),'source_openfoam_time_s':.1,'state_transfer':'continue_physical_time; U,p,phi persisted; Uf reconstructed; meshPhi=0 at zero initial motion'},'timestep_identity':{'openfoam_deltaT_s':.0025,'precice_time_window_s':.0025,'ancf_newmark_dt_s':.0025,'integer_tick_ns':2500000,'coupling_windows':40},'comparison_metrics':['max_abs_raw_Fx_N','max_abs_integrated_Fx_N','max_abs_vx_mps','max_abs_ux_m','max_fluid_Courant','time_to_5x_precursor_drag_s','time_to_10x_precursor_drag_s','time_to_100x_precursor_drag_s','time_to_abs_vx_gt_1_mps_s','streamwise_cumulative_work_J','Fx_sign_reversals','mesh_auxiliary_max_iterations','mesh_auxiliary_final_residual_envelope'],'containment':{'negative_cells':'stop','nonfinite':'stop','participant_fpe':'stop','max_abs_ux_m':.1,'max_abs_vx_mps':20.,'max_abs_raw_Fx_N':2e6}})
    c.pop('quality_contract_v3',None)
    OUT.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
if __name__=='__main__': main()
