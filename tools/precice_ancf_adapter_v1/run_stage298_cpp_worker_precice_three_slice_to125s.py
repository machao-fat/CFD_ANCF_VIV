"""Run Stage 298: continue the accepted 70 s state for 55 s to 125 s."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUNTIME = ROOT / "runtime" / "297_cpp_worker_precice_three_slice_continue40s_v1"
SOURCE_STATE = SOURCE_RUNTIME / "logs" / "structure_participant.json"
SOURCE_FIXTURE = ROOT / "runtime" / "cpp_worker_to70s_real_v1" / "run_001" / "support" / "cpp_input_fixture.json"
WORKER = ROOT / "runtime" / "292_cpp_worker_linux_build_v1" / "cfd_ancf_ancf_kernel_worker"
RUNTIME = ROOT / "runtime" / "298_cpp_worker_precice_three_slice_to125s_v1"
LOGS = RUNTIME / "logs"
RESULTS = ROOT / "results" / "298_cpp_worker_precice_three_slice_to125s_v1"
RUN_ID = "stage298_cpp_worker_precice_three_slice_to125s_run_v1"
CASE_ID = "stage298_cpp_worker_precice_three_slice_to125s_case_v1"


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_xml(index: int, socket: str) -> str:
    name = f"{index:04d}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{socket}"/>
<participant name="Structure_{name}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="0.005"/><max-time value="55.0"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''


def prepare() -> list[Path]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse Stage 298 runtime/results")
    if not SOURCE_RUNTIME.is_dir() or not SOURCE_STATE.is_file() or not SOURCE_FIXTURE.is_file() or not WORKER.is_file():
        raise RuntimeError("Stage 294 source state, fixture, or worker missing")
    cases = []
    for index in range(3):
        source = SOURCE_RUNTIME / f"slice_{index:04d}"
        destination = RUNTIME / f"slice_{index:04d}"
        shutil.copytree(source, destination)
        for child in list(destination.iterdir()):
            if child.name not in {"70", "constant", "system", "precice-config.xml"}:
                if child.is_dir(): shutil.rmtree(child)
                else: child.unlink()
        if not (destination / "70").is_dir():
            raise RuntimeError("70 s source field directory missing")
        control = destination / "system" / "controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"startFrom\s+[^;]+;", "startFrom       latestTime;", text)
        text = re.sub(r"startTime\s+[^;]+;", "startTime       70;", text)
        text = re.sub(r"endTime\s+[^;]+;", "endTime         125.0;", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        control.write_text(text, encoding="utf-8")
        (destination / "precice-config.xml").write_text(config_xml(index, wsl(RUNTIME / "precice-sockets")), encoding="utf-8")
        (destination / "system" / "preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(destination)
    for path in (LOGS, RUNTIME / "process", RUNTIME / "storage"):
        path.mkdir(parents=True, exist_ok=True)
    return cases


def main() -> int:
    cases = prepare()
    started = datetime.now(timezone.utc)
    (LOGS / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project, logs, worker, fixture, state = map(wsl, (ROOT, LOGS, WORKER, SOURCE_FIXTURE, SOURCE_STATE))
    participant = f"{project}/tools/precice_ancf_adapter_v1/ancf_cpp_worker_three_slice_continue40s_v1.py"
    configs = [wsl(case / "precice-config.xml") for case in cases]
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    # Normal solver stdout is discarded to enforce bounded storage; stderr and all structured evidence remain.
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        f"export PYTHONPATH='{project}/src:{pydeps}';",
        f"python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs}/structure_participant.json' --barrier-log '{logs}/global_barrier.json' --checkpoint-log '{logs}/checkpoint.jsonl' --worker '{worker}' --fixture '{fixture}' --initial-state '{state}' --source-step 14000 --source-time 70.0 --steps 11000 --dt 0.005 --run-id '{RUN_ID}' --case-id '{CASE_ID}' > /dev/null 2> '{logs}/structure.stderr' & spid=\\$!;",
        f"(cd '{wsl(cases[0])}' && pimpleFoam > /dev/null 2> '{logs}/fluid_0000.stderr') & fpid0=\\$!;",
        f"(cd '{wsl(cases[1])}' && pimpleFoam > /dev/null 2> '{logs}/fluid_0001.stderr') & fpid1=\\$!;",
        f"(cd '{wsl(cases[2])}' && pimpleFoam > /dev/null 2> '{logs}/fluid_0002.stderr') & fpid2=\\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\\$spid\" \"\\$fpid0\" \"\\$fpid1\" \"\\$fpid2\" > '{logs}/pids.txt';",
        "set +e; wait \"\\$spid\"; sr=\$?; wait \"\\$fpid0\"; r0=\$?; wait \"\\$fpid1\"; r1=\$?; wait \"\\$fpid2\"; r2=\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\\$sr\" \"\\$r0\" \"\\$r1\" \"\\$r2\" > '{logs}/returns.txt';",
        "if [ \"\\$sr\" -ne 0 ] || [ \"\\$r0\" -ne 0 ] || [ \"\\$r1\" -ne 0 ] || [ \"\\$r2\" -ne 0 ]; then exit 1; fi",
    ])
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (LOGS / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (LOGS / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (LOGS / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    structure_path = LOGS / "structure_participant.json"
    structure = json.loads(structure_path.read_text(encoding="utf-8")) if structure_path.is_file() else {}
    counts = structure.get("slice_counts", {})
    fluid_err = [(LOGS / f"fluid_{i:04d}.stderr").read_text(encoding="utf-8", errors="replace") if (LOGS / f"fluid_{i:04d}.stderr").is_file() else "" for i in range(3)]
    checkpoints = [json.loads(line) for line in (LOGS / "checkpoint.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()] if (LOGS / "checkpoint.jsonl").is_file() else []
    steps = [int(item.get("global_step", -1)) for item in checkpoints]
    schedule = len(steps) == 110 and steps[0:1] == [14100] and steps[-1:] == [25000] and all(b - a == 100 for a, b in zip(steps, steps[1:]))
    returns = (LOGS / "returns.txt").read_text(encoding="utf-8", errors="replace") if (LOGS / "returns.txt").is_file() else ""
    checks = {
        "finalized": structure.get("finalized") is True,
        "committed_target_25000": structure.get("committed_steps") == 25000,
        "local_steps_11000": structure.get("local_committed_steps") == 11000,
        "slice_counts_11000": all(counts.get(f"slice_{i:04d}") == 11000 for i in range(3)),
        "tail_records_20": len(structure.get("tail_records", [])) == 20,
        "checkpoint_count_110": structure.get("checkpoint_count") == 110,
        "checkpoint_schedule_14100_to_25000": schedule,
        "worker_closed": structure.get("worker", {}).get("closed") is True and structure.get("worker", {}).get("return_code") == 0,
        "barrier_hash_present": len(structure.get("barrier_sha256", "")) == 64,
        "fluid_stderr_empty": all(not text.strip() for text in fluid_err),
        "fluid_final_time_125": all((case / "125").is_dir() for case in cases),
        "returns_zero": all(re.search(rf"{name}=0", returns) for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "purge_write": all("purgeWrite      1;" in (case / "system" / "controlDict").read_text(encoding="utf-8") for case in cases),
    }
    gate = {
        "gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_TO125S_V1_GATE",
        "status": "pass" if run.returncode == 0 and all(checks.values()) else "do_not_pass",
        "stage_id": "stage4f_d_cpp_worker_precice_three_slice_to125s_v1",
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "scope_contract": {"source_step": 14000, "source_time_s": 70.0, "target_step": 25000, "target_time_s": 125.0, "advance_time_s": 55.0, "openfoam": "10", "precice": "3.4.1", "dt_s": 0.005, "slice_count": 3, "storage": "source 70 s fields + purgeWrite=1 + tail 20 + checkpoints every 100 local steps + final restart"},
        "checks": checks,
        "runtime": str(RUNTIME),
        "source_hashes": {"worker": sha(WORKER), "fixture": sha(SOURCE_FIXTURE), "source_state": sha(SOURCE_STATE), "participant": sha(ROOT / "tools" / "precice_ancf_adapter_v1" / "ancf_cpp_worker_three_slice_continue40s_v1.py")},
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "return_code": run.returncode,
        "wall_clock": {"start_utc": started.isoformat(), "end_utc": ended.isoformat(), "elapsed_s": (ended - started).total_seconds()},
        "storage_audit": {"runtime_bytes": sum(path.stat().st_size for path in RUNTIME.rglob("*") if path.is_file()), "tail_records": len(structure.get("tail_records", [])), "checkpoint_count": structure.get("checkpoint_count"), "final_state_saved": all(key in structure for key in ("final_q", "final_qdot", "final_qddot"))},
        "protected": {"stage294_source_modified": False, "historical_evidence_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False, "formal_viv_validation_complete": False},
        "qualification": "55 s continuation to 125 s for long-window stability/frequency observation; not formal 15-cycle convergence",
        "next_authorization": "new explicit authorization required before longer duration or formal statistics",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_cpp_worker_precice_three_slice_to125s_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "structure_participant.json").write_text(json.dumps(structure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "wall_clock_s": gate["wall_clock"]["elapsed_s"], "return_code": run.returncode}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
