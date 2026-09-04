"""Run one fresh 10 s three-slice C++ worker/preCICE segment."""
from __future__ import annotations
import hashlib, json, re, shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "294_cpp_worker_precice_three_slice_10s_v1"
SOURCE = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "case"
FIXTURE = ROOT / "runtime" / "cpp_worker_to70s_real_v1" / "run_001" / "support" / "cpp_input_fixture.json"
WORKER = ROOT / "runtime" / "292_cpp_worker_linux_build_v1" / "cfd_ancf_ancf_kernel_worker"
LOGS = RUNTIME / "logs"
RUN_ID = "stage294_cpp_worker_precice_three_slice_10s_run_v1"
CASE_ID = "stage294_cpp_worker_precice_three_slice_10s_case_v1"

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]
def config_xml(index: int, socket: str) -> str:
    name = f"{index:04d}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{socket}"/>
<participant name="Structure_{name}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="0.005"/><max-time value="10.0"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''
def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''
def prepare() -> list[Path]:
    if RUNTIME.exists(): raise RuntimeError(f"refusing to reuse runtime: {RUNTIME}")
    if not SOURCE.is_dir() or not FIXTURE.is_file() or not WORKER.is_file(): raise RuntimeError("required source missing")
    cases=[]
    for index in range(3):
        case=RUNTIME/f"slice_{index:04d}"
        for name in ("0","constant","system"): shutil.copytree(SOURCE/name,case/name)
        control=case/"system"/"controlDict"; text=control.read_text(encoding="utf-8")
        text=re.sub(r"endTime\s+[^;]+;","endTime         10.0;",text); text=re.sub(r"purgeWrite\s+[^;]+;","purgeWrite      1;",text); control.write_text(text,encoding="utf-8")
        (case/"precice-config.xml").write_text(config_xml(index,wsl(RUNTIME/"precice-sockets")),encoding="utf-8")
        (case/"system"/"preciceDict").write_text(precice_dict(index),encoding="utf-8"); cases.append(case)
    for path in (LOGS,RUNTIME/"process",RUNTIME/"storage"): path.mkdir(parents=True,exist_ok=True)
    return cases
def main()->int:
    cases=prepare(); started=datetime.now(timezone.utc); (LOGS/"start_utc.txt").write_text(started.isoformat()+"\n",encoding="utf-8")
    project=wsl(ROOT); logs=wsl(LOGS); fixture=wsl(FIXTURE); worker=wsl(WORKER); participant=f"{project}/tools/precice_ancf_adapter_v1/ancf_cpp_worker_three_slice_long_participant_v1.py"; configs=[wsl(c/"precice-config.xml") for c in cases]; pydeps=f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell=" ".join(["set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",f"export PYTHONPATH='{project}/src:{pydeps}';",f"python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs}/structure_participant.json' --barrier-log '{logs}/global_barrier.json' --checkpoint-log '{logs}/checkpoint.jsonl' --worker '{worker}' --fixture '{fixture}' --steps 2000 --dt 0.005 --run-id '{RUN_ID}' --case-id '{CASE_ID}' > '{logs}/structure.stdout' 2> '{logs}/structure.stderr' & spid=\\$!;",f"(cd '{wsl(cases[0])}' && pimpleFoam > '{logs}/fluid_0000.stdout' 2> '{logs}/fluid_0000.stderr') & fpid0=\\$!;",f"(cd '{wsl(cases[1])}' && pimpleFoam > '{logs}/fluid_0001.stdout' 2> '{logs}/fluid_0001.stderr') & fpid1=\\$!;",f"(cd '{wsl(cases[2])}' && pimpleFoam > '{logs}/fluid_0002.stdout' 2> '{logs}/fluid_0002.stderr') & fpid2=\\$!;",f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\\$spid\" \"\\$fpid0\" \"\\$fpid1\" \"\\$fpid2\" > '{logs}/pids.txt';","set +e; wait \"\\$spid\"; sr=\\$?; wait \"\\$fpid0\"; r0=\\$?; wait \"\\$fpid1\"; r1=\\$?; wait \"\\$fpid2\"; r2=\\$?; set -e;",f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\\$sr\" \"\\$r0\" \"\\$r1\" \"\\$r2\" > '{logs}/returns.txt';","if [ \"\\$sr\" -ne 0 ] || [ \"\\$r0\" -ne 0 ] || [ \"\\$r1\" -ne 0 ] || [ \"\\$r2\" -ne 0 ]; then exit 1; fi"])
    run=subprocess.run(["wsl.exe","bash","-lc",shell],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace"); (LOGS/"launcher.stdout").write_text(run.stdout,encoding="utf-8"); (LOGS/"launcher.stderr").write_text(run.stderr,encoding="utf-8"); ended=datetime.now(timezone.utc); (LOGS/"end_utc.txt").write_text(ended.isoformat()+"\n",encoding="utf-8")
    structure=json.loads((LOGS/"structure_participant.json").read_text(encoding="utf-8")) if (LOGS/"structure_participant.json").is_file() else {}; counts=structure.get("slice_counts",{}); fluid=[(LOGS/f"fluid_{i:04d}.stdout").read_text(encoding="utf-8",errors="replace") if (LOGS/f"fluid_{i:04d}.stdout").is_file() else "" for i in range(3)]; ferr=[(LOGS/f"fluid_{i:04d}.stderr").read_text(encoding="utf-8",errors="replace") if (LOGS/f"fluid_{i:04d}.stderr").is_file() else "" for i in range(3)]
    checkpoint_log = RUNTIME / "logs" / "checkpoint.jsonl"
    checkpoints = []
    if checkpoint_log.exists():
        checkpoints = [json.loads(line) for line in checkpoint_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    checkpoint_steps = [int(item.get("global_step", -1)) for item in checkpoints]
    checkpoint_schedule = (
        len(checkpoint_steps) == 20
        and checkpoint_steps[0:1] == [100]
        and checkpoint_steps[-1:] == [2000]
        and all(b - a == 100 for a, b in zip(checkpoint_steps, checkpoint_steps[1:]))
    )
    checks={"finalized":structure.get("finalized") is True,"committed_2000":structure.get("committed_steps")==2000,"slice_counts_2000":all(counts.get(f"slice_{i:04d}")==2000 for i in range(3)),"tail_records_20":len(structure.get("tail_records",[]))==20,"checkpoint_count_20":structure.get("checkpoint_count")==20,"checkpoint_schedule_100_to_2000":checkpoint_schedule,"worker_closed":structure.get("worker",{}).get("closed") is True and structure.get("worker",{}).get("return_code")==0,"barrier_hash_present":len(structure.get("barrier_sha256", ""))==64,"fluid_end":all(re.search(r"^End$",x,re.M) for x in fluid),"fluid_stderr_empty":all(not x.strip() for x in ferr),"purge_write":all("purgeWrite      1;" in (c/"system"/"controlDict").read_text(encoding="utf-8") for c in cases)}
    gate={"gate_id":"STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_10S_V1_GATE","status":"pass" if run.returncode==0 and all(checks.values()) else "do_not_pass","timestamp":ended.isoformat(),"stage_id":"stage4f_d_cpp_worker_precice_three_slice_10s_v1","run_id":RUN_ID,"case_id":CASE_ID,"scope_contract":{"openfoam":"10","precice":"3.4.1","dt_s":0.005,"steps":2000,"end_time_s":10.0,"slice_count":3,"storage":"rolling tail 20 + checkpoint every 100 steps"},"checks":checks,"runtime":str(RUNTIME),"source_hashes":{"worker":sha(WORKER),"fixture":sha(FIXTURE),"participant":sha(ROOT/"tools"/"precice_ancf_adapter_v1"/"ancf_cpp_worker_three_slice_long_participant_v1.py")},"real_process_counts":{"matlab":0,"openfoam":3,"wsl":1,"cfd":3,"cpp_worker":1,"precice_structure":1},"owned_residual":0,"return_code":run.returncode,"wall_clock":{"start_utc":started.isoformat(),"end_utc":ended.isoformat(),"elapsed_s":(ended-started).total_seconds()},"storage_audit":{"runtime_bytes":sum(p.stat().st_size for p in RUNTIME.rglob("*") if p.is_file()),"tail_records":len(structure.get("tail_records",[])),"checkpoint_count":structure.get("checkpoint_count"),"final_state_saved":all(k in structure for k in ("final_q","final_qdot","final_qddot"))},"protected":{"historical_evidence_modified":False,"ancf_eb_core_modified":False,"physical_parameters_modified":False,"global_dt_modified":False,"numerical_thresholds_modified":False,"formal_protocol_modified":False,"formal_viv_validation_complete":False},"qualification":"10 s three-slice long-window stability/continuation smoke; not 15-cycle formal VIV convergence","next_authorization":"new explicit authorization required before longer duration or formal statistics"}
    out=ROOT/"results"/"294_cpp_worker_precice_three_slice_10s_v1"; out.mkdir(parents=True,exist_ok=True); (out/"stage4f_d_cpp_worker_precice_three_slice_10s_v1_gate.json").write_text(json.dumps(gate,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); (out/"structure_participant.json").write_text(json.dumps(structure,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"gate":gate["status"],"checks":checks,"wall_clock_s":gate["wall_clock"]["elapsed_s"],"return_code":run.returncode},ensure_ascii=False)); return 0 if gate["status"]=="pass" else 1
if __name__=="__main__": raise SystemExit(main())
