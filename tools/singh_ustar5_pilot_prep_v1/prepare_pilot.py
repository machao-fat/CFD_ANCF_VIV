#!/usr/bin/env python3
"""Prepare Singh U*=5 pilot artifacts only; never launch a solver."""
import hashlib,json,math,re,shutil,sys
from pathlib import Path
ROOT=Path(r"D:/CFD/CFD_ANCF_VIV")
BASE=ROOT/"runtime/fixed_cylinder_o_grid/2_dof_validation/coupled_regression_v1/phase_b"
PILOT=ROOT/"runtime/fixed_cylinder_o_grid/2_dof_validation/singh_ustar5_pilot_v1"
START=159.999999999999091; DT=.005; D=U=LZ=1.; RHO=1000.; NU=.01
USTAR=5.; MSTAR=10.; FN=.2; TN=5.; OMEGA=2*math.pi*FN
M=MSTAR*math.pi*RHO*D*D*LZ/4.; K=M*OMEGA*OMEGA
FX0=682.8602575932; FY0=149.04306319129; AX0=FX0/M; AY0=FY0/M
STAGES={"stage1":(5.,1000),"stage2":(25.,5000),"stage3":(75.,15000),"optional":(100.,20000)}
def put(p,s):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="\n") as f: f.write(s)
def putj(p,x): put(p,json.dumps(x,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): h.update(b)
 return h.hexdigest()
def contract(name,end,n):
 return {"schema_version":"singh-ustar5-pilot-prep-v1","run_id":"singh_ustar5_pilot_"+name,"status":"PREPARED_NOT_LAUNCHED","phase":"SINGH_USTAR5_2DOF","source_case":str(BASE),"physical":{"Re":100.0,"D_m":D,"U_mps":U,"rho_kgpm3":RHO,"nu_m2ps":NU,"Lz_m":LZ},"singh_contract":{"m_star":MSTAR,"U_star":USTAR,"Fn":FN,"fn_Hz":FN,"Tn_s":TN,"omega_n_radps":OMEGA,"definition":"m*=4*m'/(pi*rho*D^2), Fn=fn*D/U, U*=U/(fn*D)","responses":{"transverse":"Ymax/D","inline":"Xrms/D","retain":"mean X/D"}},"structure":{"Mx_kg":M,"My_kg":M,"Kx_Npm":K,"Ky_Npm":K,"Cx_Nspm":0.,"Cy_Nspm":0.,"cross_terms":False,"added_mass":False,"mean_drag_subtraction":False},"initial_state":{"source":str(BASE/"159.999999999999091"),"openfoam_global_time_s":START,"pilot_elapsed_time_s":0.,"x_m":0.,"y_m":0.,"vx_mps":0.,"vy_mps":0.,"Fx0_total_N":FX0,"Fy0_total_N":FY0,"ax0_mps2":AX0,"ay0_mps2":AY0,"initial_field_policy":"mature Re=100 fixed-cylinder wake; not uniform-flow t=0"},"mapping":{"Fx_to":"X","Fy_to":"Y","x":"streamwise displacement","y":"cross-flow displacement","vertices":72},"coupling":{"start_of_time_s":START,"pilot_elapsed_start_s":0.,"dt_s":DT,"end_of_time_s":START+end,"pilot_elapsed_end_s":end,"accepted_window_limit":n,"min_iterations":2,"max_iterations":8,"acceleration":"none","scheme":"parallel-implicit"},"mesh":{"cells":19600,"domain_blockage":1/30,"singh_blockage":.05,"difference_status":"DOCUMENTED_IMPLEMENTATION_DIFFERENCE"},"preparation_boundary":{"NO_OPENFOAM_RUN":True,"NO_PRECICE_RUN":True,"NO_FSI_RUN":True,"NO_NEW_TIME_DIRECTORY":True}}
LAUNCH='''#!/usr/bin/env bash
set -euo pipefail
# 手动选择一个阶段；不自动串联，本轮准备过程未执行。
CASE="$(cd "$(dirname "$0")" && pwd)"
STAGE="$1"
case "$STAGE" in stage1|stage2|stage3|optional) ;; *) echo "usage: launch_stage.sh stage1|stage2|stage3|optional" >&2; exit 2;; esac
PROJECT="/mnt/d/研二文件/开题准备/CFD_ANCF_VIV"
ABI_ROOT="/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001"
export LD_LIBRARY_PATH="$ABI_ROOT/platforms/linux64GccDPInt32Opt/lib"
export PYTHONPATH="$PROJECT/runtime/fixed_cylinder_o_grid/2_dof_validation"
S="$CASE/stage_configs"
cp "$S/$STAGE"_controlDict "$CASE/system/controlDict"
cp "$S/$STAGE"_precice-config.xml "$CASE/precice-config.xml"
cp "$S/$STAGE"_contract.json "$CASE/singh_Ustar5_contract.json"
cp "$S/$STAGE"_contract.json "$CASE/contract.json"
 if [ -e "$CASE/structure/events.jsonl" ]; then echo "non-empty structure runtime; use clean case" >&2; exit 3; fi
 EXTRA=$(find "$CASE" -maxdepth 1 -mindepth 1 -type d -printf "%f\\n" | grep -E '^[0-9]' | grep -v '^159\\.999999999999091$' || true)
 if [ -n "$EXTRA" ]; then echo "extra numeric time directories found; use a clean case" >&2; exit 3; fi
 mkdir -p "$CASE/structure" "$CASE/precice-sockets-v3"
python3 "$CASE/two_dof_precice_participant.py" --config "$CASE/precice-config.xml" --runtime "$CASE/structure" --contract "$CASE/singh_Ustar5_contract.json" --vertex-count 72 > "$CASE/participant_$STAGE.stdout" 2> "$CASE/participant_$STAGE.stderr" &
P="$!"
trap 'kill "$P" 2>/dev/null || true' EXIT
source "$ABI_ROOT/etc/bashrc" 2>/dev/null || true
cd "$CASE"
pimpleFoam -case "$CASE" > "$CASE/fluid_$STAGE.stdout" 2> "$CASE/fluid_$STAGE.stderr"
wait "$P"
trap - EXIT
'''
ANALYZER='''#!/usr/bin/env python3
"""Offline Singh U*=5 postprocessor; never invokes a solver."""
import argparse,csv,json
from pathlib import Path
import numpy as np
def load(p):
 r=[]
 for line in p.open(encoding="utf-8"):
  if line.strip():
   e=json.loads(line)
   if e.get("event")=="window_commit":
    s=e["accepted_state"]; r.append({"time_s":float(e["physical_time_s"]),"x_m":float(s["x_m"]),"y_m":float(s["y_m"]),"vx_mps":float(s["vx_mps"]),"vy_mps":float(s["vy_mps"]),"ax_mps2":float(s["ax_mps2"]),"ay_mps2":float(s["ay_mps2"]),"Fx_N":float(e["force_N"][0]),"Fy_N":float(e["force_N"][1]),"iteration_count":int(e.get("iteration_count",0))})
 return r
def main():
 p=argparse.ArgumentParser(); p.add_argument("--runtime",type=Path,required=True); p.add_argument("--out",type=Path,required=True); a=p.parse_args(); r=load(a.runtime/"events.jsonl")
 if not r: raise SystemExit("no accepted window_commit records")
 a.out.mkdir(parents=True,exist_ok=True); t=np.array([z["time_s"] for z in r]); x=np.array([z["x_m"] for z in r]); y=np.array([z["y_m"] for z in r]); cd=np.array([z["Fx_N"] for z in r])/500.; cl=np.array([z["Fy_N"] for z in r])/500.
 def dom(q):
  q=q-q.mean(); f=np.fft.rfftfreq(len(q),t[1]-t[0]); s=np.abs(np.fft.rfft(q)); return float(f[1+np.argmax(s[1:])])
 m={"accepted_samples":len(r),"time_range_s":[float(t[0]),float(t[-1])],"SINGH_YMAX_OVER_D":float(y.max()),"X_RMS_OVER_D":float(np.sqrt(np.mean(x*x))),"MEAN_X_OVER_D":float(x.mean()),"Xprime_rms_over_D":float(np.std(x)),"Ax_half_peak_to_peak_over_D":float((x.max()-x.min())/2),"Ay_half_peak_to_peak_over_D":float((y.max()-y.min())/2),"mean_Cd":float(cd.mean()),"Cd_rms":float(np.sqrt(np.mean(cd*cd))),"Cl_rms":float(np.sqrt(np.mean(cl*cl))),"fX_D_over_U":dom(x),"fY_D_over_U":dom(y),"accepted_only":True,"normalization":"F/500 N"}
 with (a.out/"accepted_history.csv").open("w",newline="",encoding="utf-8") as f: w=csv.DictWriter(f,fieldnames=list(r[0])); w.writeheader(); w.writerows(r)
 (a.out/"singh_Ustar5_metrics.json").write_text(json.dumps(m,indent=2)+"\\n",encoding="utf-8"); print(json.dumps(m,indent=2))
if __name__=="__main__": main()
'''
def main():
 # A partial first attempt may be refreshed; a completed pilot is protected.
 if (PILOT/"SINGH_USTAR5_PILOT_PREP_V1_REPORT.md").exists() and sys.argv[1:] != ["--refresh"]: raise SystemExit("refusing completed pilot: "+str(PILOT))
 PILOT.mkdir(parents=True, exist_ok=True); shutil.copytree(BASE/"constant",PILOT/"constant",dirs_exist_ok=True); (PILOT/"system").mkdir(exist_ok=True)
 for p in (BASE/"system").iterdir():
  if p.is_file(): shutil.copy2(p,PILOT/"system"/p.name)
 shutil.copytree(BASE/"159.999999999999091",PILOT/"159.999999999999091",dirs_exist_ok=True); shutil.copy2(BASE/"case.foam",PILOT/"case.foam")
 shutil.copy2(BASE.parent/"two_dof_precice_participant.py",PILOT/"two_dof_precice_participant.py")
 pp=PILOT/"two_dof_precice_participant.py"; s=pp.read_text(encoding="utf-8"); s=s.replace('if phase not in ("A_X_LOCK", "B_TWO_DOF"):', 'if phase not in ("A_X_LOCK", "B_TWO_DOF", "SINGH_USTAR5_2DOF"):'); pp.open("w",encoding="utf-8",newline="\n").write(s)
 sc=PILOT/"stage_configs"; sc.mkdir(exist_ok=True); ex="/mnt/d/CFD/CFD_ANCF_VIV/runtime/fixed_cylinder_o_grid/2_dof_validation/singh_ustar5_pilot_v1/precice-sockets-v3"; base_control=(BASE/"system/controlDict").read_text(encoding="utf-8"); base_xml=(BASE/"precice-config.xml").read_text(encoding="utf-8")
 for name,(end,n) in STAGES.items():
  c=contract(name,end,n); putj(sc/(name+"_contract.json"),c)
  ctl=re.sub(r"endTime\s+\S+;",f"endTime {START+end:.12f};",base_control); ctl=re.sub(r"// 50 accepted windows[^\n]*",f"// Stage {name}: {n} accepted windows at dt=0.005 s.",ctl); put(sc/(name+"_controlDict"),ctl)
  xx=re.sub(r'<m2n:sockets acceptor="Structure_0000" connector="Fluid_0000" exchange-directory="[^"]+"',f'<m2n:sockets acceptor="Structure_0000" connector="Fluid_0000" exchange-directory="{ex}"',base_xml); xx=re.sub(r'<max-time value="[^"]+"',f'<max-time value="{end:.12f}"',xx); put(sc/(name+"_precice-config.xml"),xx)
 shutil.copy2(sc/"stage1_controlDict",PILOT/"system/controlDict")
 shutil.copy2(sc/"stage1_precice-config.xml",PILOT/"precice-config.xml")
 put(PILOT/"launch_stage.sh",LAUNCH)
 for n,f in {"stage1":"run_stage1_1Tn.sh","stage2":"run_stage2_to_5Tn.sh","stage3":"run_stage3_to_15Tn.sh","optional":"run_optional_to_20Tn.sh"}.items(): put(PILOT/f,'#!/usr/bin/env bash\nset -euo pipefail\n# 手动脚本；本轮只生成，未执行。\nCASE="$(cd "$(dirname "$0")" && pwd)"\nexec bash "$CASE/launch_stage.sh" '+n+'\n')
 put(PILOT/"analyze_singh_Ustar5.py",ANALYZER); c=contract("stage1",5.,1000); c["staged_releases"]=[{"name":n,"pilot_elapsed_end_s":v[0],"accepted_windows":v[1],"manual_only":True} for n,v in STAGES.items()]; putj(PILOT/"singh_Ustar5_contract.json",c); shutil.copy2(PILOT/"singh_Ustar5_contract.json",PILOT/"contract.json")
 report=f"""# SINGH_USTAR5_PILOT_PREP_V1

状态：SINGH_USTAR5_PILOT_PREP = READY（仅准备，未运行）。

Pilot case: {PILOT}
Base case: {BASE}（已通过的 2DOF coupled regression Phase B）。
Re=100, D=1 m, U=1 m/s, rho=1000 kg/m3, nu=0.01 m2/s, Lz=1 m。
m*=10, Mx=My={M:.15f} kg；U*=5, fn={FN:.15f} Hz, Tn={TN:.15f} s, omega={OMEGA:.15f} rad/s。
Kx=Ky={K:.15f} N/m, Cx=Cy=0；旧 M=2500、K=4940 未在 active contract 生效。
初始场: {BASE/"159.999999999999091"} 的成熟 fixed-cylinder wake；global time={START:.15f} s，pilot_elapsed_time=0。
初始 x/y/vx/vy=0；Fx0={FX0:.12f} N, Fy0={FY0:.12f} N；ax0={AX0:.15f}, ay0={AY0:.15f} m/s2。
映射: Fx to X, Fy to Y, x streamwise, y cross-flow, 72 vertices。
保持 constant、polyMesh、dynamicMeshDict、物性、fvSchemes、fvSolution、preciceDict、dt=0.005、writeInterval=0.1、PIMPLE、parallel-implicit 2/8。
仅改变 contract、participant phase whitelist、pilot socket/max-time/endTime 和 staged scripts；blockage 3.333% vs Singh 5% 标记 DOCUMENTED_IMPLEMENTATION_DIFFERENCE，不是 blocker。
Stages: stage1 0 to 5 s/1000; stage2 0 to 25 s/5000; stage3 0 to 75 s/15000; optional 0 to 100 s/20000。各阶段手动选择，不自动串联。
analyze_singh_Ustar5.py 仅读取 accepted window_commit，排除 trial/restore。
PRE_RUN_AUDIT = PASS_FOR_PREPARATION_ONLY。未调用 OpenFOAM、preCICE、FSI，未创建新 time directory。
"""
 put(PILOT/"SINGH_USTAR5_PILOT_PREP_V1_REPORT.md",report); put(PILOT/"postprocessing_contract.md","accepted window_commit only; exclude trial/restore. Report Ymax/D, Xrms/D, mean X/D, Xprime RMS/D, Ax/Ay half p2p, mean Cd, Cd RMS, Cl RMS, fX*D/U, fY*D/U. Normalize F/(0.5*rho*U^2*D*Lz)=F/500 N.\\n")
 put(PILOT/"PRE_RUN_CHECKLIST.txt",f"""SINGH_USTAR5_PILOT_PREP_V1
STATUS=READY (PREPARATION ONLY)
CASE={PILOT}
BASE={BASE}
Confirm ABI/ldd-r, clean runtime/socket, M={M:.15f}, K={K:.15f}, C=0.
Confirm global start={START:.15f}, pilot elapsed start=0, Fx0={FX0:.12f}, Fy0={FY0:.12f}, ax0={AX0:.15f}, ay0={AY0:.15f}.
Select exactly one staged script; do not auto-chain; do not reuse old M=2500/K=4940.
NO_OPENFOAM_RUN NO_PRECICE_RUN NO_FSI_RUN NO_NEW_TIME_DIRECTORY
""")
 files=[p for p in PILOT.rglob("*") if p.is_file() and p.name != "SINGH_USTAR5_PILOT_PREP_V1.json"]; man={str(p.relative_to(PILOT)).replace("\\","/"):sha(p) for p in sorted(files)}
 putj(PILOT/"SINGH_USTAR5_PILOT_PREP_V1.json",{"status":"SINGH_USTAR5_PILOT_PREP=READY","PRE_RUN_AUDIT":"PASS_FOR_PREPARATION_ONLY","NO_OPENFOAM_RUN":True,"NO_PRECICE_RUN":True,"NO_FSI_RUN":True,"NO_NEW_TIME_DIRECTORY":True,"pilot_case":str(PILOT),"base_case":str(BASE),"structure":c["structure"],"singh_contract":c["singh_contract"],"initial_state":c["initial_state"],"mapping":c["mapping"],"mesh":c["mesh"],"active_parameter_check":{"old_M_2500_active":False,"old_K_4940_active":False,"new_M_kg":M,"new_K_Npm":K},"deliverables":sorted(man),"sha256":man})
 print(PILOT); print(json.dumps({"M_kg":M,"K_Npm":K,"ax0":AX0,"ay0":AY0},indent=2))
if __name__=="__main__": main()
