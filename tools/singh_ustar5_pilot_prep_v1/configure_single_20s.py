#!/usr/bin/env python3
"""Convert the prepared Singh pilot to one standalone 20 s release."""
import hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(r"D:/CFD/CFD_ANCF_VIV")
CASE=ROOT/"runtime/fixed_cylinder_o_grid/2_dof_validation/singh_ustar5_pilot_v1"
START=159.999999999999091; ELAPSED=20.0; END=179.999999999999; WINDOWS=4000; DT=.005
def put(p,s):
    with p.open("w",encoding="utf-8",newline="\n") as f: f.write(s)
def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""): h.update(b)
    return h.hexdigest()
def main():
    if not (CASE/"singh_Ustar5_contract.json").exists(): raise SystemExit("pilot contract missing")
    stage=CASE/"stage_configs"
    if stage.exists(): shutil.rmtree(stage)
    for name in ["launch_stage.sh","run_stage1_1Tn.sh","run_stage2_to_5Tn.sh","run_stage3_to_15Tn.sh","run_optional_to_20Tn.sh"]:
        p=CASE/name
        if p.exists(): p.unlink()
    ctl=CASE/"system/controlDict"; s=ctl.read_text(encoding="utf-8")
    s=re.sub(r"endTime\s+\S+;",f"endTime {END:.12f};",s)
    s=re.sub(r"// Stage stage1:[^\n]*",f"// Single release: {WINDOWS} accepted windows, 20 s pilot elapsed.",s)
    put(ctl,s)
    xp=CASE/"precice-config.xml"; s=xp.read_text(encoding="utf-8")
    s=re.sub(r'<max-time value="[^"]+"',f'<max-time value="{ELAPSED:.12f}"',s); put(xp,s)
    c=json.loads((CASE/"singh_Ustar5_contract.json").read_text(encoding="utf-8"))
    c["run_id"]="singh_ustar5_pilot_20s"; c.pop("staged_releases",None)
    c["release"]={"name":"single_20s","pilot_elapsed_end_s":ELAPSED,"accepted_window_limit":WINDOWS,"manual_only":True}
    c["coupling"].update({"end_of_time_s":END,"pilot_elapsed_end_s":ELAPSED,"accepted_window_limit":WINDOWS})
    put(CASE/"singh_Ustar5_contract.json",json.dumps(c,indent=2,ensure_ascii=False,sort_keys=True)+"\n"); shutil.copy2(CASE/"singh_Ustar5_contract.json",CASE/"contract.json")
    launch='''#!/usr/bin/env bash
set -euo pipefail
# Singh U*=5 单一 20 s pilot；仅人工确认后启动。
CASE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="/mnt/d/研二文件/开题准备/CFD_ANCF_VIV"
ABI_ROOT="/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001"
export LD_LIBRARY_PATH="$ABI_ROOT/platforms/linux64GccDPInt32Opt/lib"
export PYTHONPATH="$PROJECT/runtime/fixed_cylinder_o_grid/2_dof_validation"
if [ -e "$CASE/structure/events.jsonl" ]; then echo "structure runtime exists; use clean case" >&2; exit 3; fi
EXTRA=$(find "$CASE" -maxdepth 1 -mindepth 1 -type d -printf "%f\\n" | grep -E '^[0-9]' | grep -v '^159\.999999999999091$' || true)
if [ -n "$EXTRA" ]; then echo "extra numeric time directories found; use clean case" >&2; exit 3; fi
if find "$CASE/precice-sockets-v3" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then echo "socket directory is not empty" >&2; exit 3; fi
mkdir -p "$CASE/structure" "$CASE/precice-sockets-v3"
python3 "$CASE/two_dof_precice_participant.py" --config "$CASE/precice-config.xml" --runtime "$CASE/structure" --contract "$CASE/singh_Ustar5_contract.json" --vertex-count 72 > "$CASE/participant.stdout" 2> "$CASE/participant.stderr" &
P="$!"
trap 'kill "$P" 2>/dev/null || true' EXIT
source "$ABI_ROOT/etc/bashrc" 2>/dev/null || true
cd "$CASE"
pimpleFoam -case "$CASE" > "$CASE/fluid.stdout" 2> "$CASE/fluid.stderr"
wait "$P"
trap - EXIT
'''
    put(CASE/"launch.sh",launch)
    report=f"""# SINGH_USTAR5_PILOT_PREP_V1

状态：SINGH_USTAR5_PILOT_PREP = READY（单一 20 s 版本，仅准备，未运行）。
Benchmark readiness：READY_WITH_DOCUMENTED_DIFFERENCES。

Pilot：{CASE}
Base：{c["source_case"]}（已通过的 Python 2DOF coupled regression Phase B）。
Re=100，D=1 m，U=1 m/s，rho=1000 kg/m3，nu=0.01 m2/s，Lz=1 m。
U*=5，fn=0.2 Hz，Tn=5 s；Mx=My={c["structure"]["Mx_kg"]:.15f} kg，Kx=Ky={c["structure"]["Kx_Npm"]:.15f} N/m，Cx=Cy=0。
单一运行：OpenFOAM global {START:.15f} -> {END:.12f} s；pilot elapsed 0 -> 20 s；{WINDOWS} accepted windows；dt=0.005 s。
初始 CFD：{c["initial_state"]["source"]} 成熟 fixed-cylinder wake；x0=y0=vx0=vy0=0；Fx0={c["initial_state"]["Fx0_total_N"]:.12f} N；Fy0={c["initial_state"]["Fy0_total_N"]:.12f} N；ax0={c["initial_state"]["ax0_mps2"]:.15f}；ay0={c["initial_state"]["ay0_mps2"]:.15f} m/s2。
映射保持 Fx to X、Fy to Y、x streamwise、y cross-flow，72 vertices。
保持 constant、polyMesh、dynamicMeshDict、物性、fvSchemes、fvSolution、preciceDict、PIMPLE、writeInterval=0.1、parallel-implicit 2/8；blockage 3.333% vs Singh 5% 为 DOCUMENTED_IMPLEMENTATION_DIFFERENCE。
已删除多阶段配置和脚本；当前只有 launch.sh。后处理只使用 accepted window_commit，排除 trial/restore。
PRE_RUN_AUDIT = PASS_FOR_PREPARATION_ONLY；未调用 OpenFOAM、preCICE 或 FSI。
"""
    put(CASE/"SINGH_USTAR5_PILOT_PREP_V1_REPORT.md",report)
    put(CASE/"PRE_RUN_CHECKLIST.txt",f"""SINGH_USTAR5_PILOT_PREP_V1 PRE-RUN CHECKLIST
STATUS=READY (SINGLE 20 s RELEASE; PREPARATION ONLY)
CASE={CASE}
BASE={c["source_case"]}
Select launch.sh only after manual ABI/ldd-r review.
Confirm global start={START:.15f}, global end={END:.12f}, pilot elapsed=20 s, windows={WINDOWS}, dt=0.005.
Confirm M={c["structure"]["Mx_kg"]:.15f} kg, K={c["structure"]["Kx_Npm"]:.15f} N/m, C=0.
Confirm Fx0={c["initial_state"]["Fx0_total_N"]:.12f} N, Fy0={c["initial_state"]["Fy0_total_N"]:.12f} N.
Use a clean structure/socket case; do not use rejected trials or old 2500/4940 parameters.
NO_OPENFOAM_RUN NO_PRECICE_RUN NO_FSI_RUN NO_NEW_TIME_DIRECTORY
""")
    j=json.loads((CASE/"SINGH_USTAR5_PILOT_PREP_V1.json").read_text(encoding="utf-8"))
    j.update({"status":"SINGH_USTAR5_PILOT_PREP=READY","PRE_RUN_AUDIT":"PASS_FOR_PREPARATION_ONLY","benchmark_readiness":"READY_WITH_DOCUMENTED_DIFFERENCES","NO_OPENFOAM_RUN":True,"NO_PRECICE_RUN":True,"NO_FSI_RUN":True,"NO_NEW_TIME_DIRECTORY":True,"single_release":{"pilot_elapsed_end_s":ELAPSED,"openfoam_end_time_s":END,"accepted_windows":WINDOWS,"dt_s":DT}})
    j["coupling"]=c["coupling"]; j["contract_file"]="singh_Ustar5_contract.json"; j.pop("deliverables",None); j.pop("sha256",None)
    files=[p for p in CASE.rglob("*") if p.is_file() and p.name!="SINGH_USTAR5_PILOT_PREP_V1.json"]
    man={str(p.relative_to(CASE)).replace("\\","/"):digest(p) for p in sorted(files)}
    j["deliverables"]=sorted(man); j["sha256"]=man
    put(CASE/"SINGH_USTAR5_PILOT_PREP_V1.json",json.dumps(j,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
if __name__=="__main__": main()
