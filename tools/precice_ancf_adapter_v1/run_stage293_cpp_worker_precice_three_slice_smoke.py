"""Run one fresh three-slice C++ worker + preCICE/OpenFOAM smoke."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "293_cpp_worker_precice_three_slice_040s_v1"
SOURCE = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "case"
FIXTURE = ROOT / "runtime" / "cpp_worker_to70s_real_v1" / "run_001" / "support" / "cpp_input_fixture.json"
WORKER = ROOT / "runtime" / "292_cpp_worker_linux_build_v1" / "cfd_ancf_ancf_kernel_worker"
LOGS = RUNTIME / "logs"
RUN_ID = "stage293_cpp_worker_precice_three_slice_040s_run_v1"
CASE_ID = "stage293_cpp_worker_precice_three_slice_040s_case_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def config_xml(index: int, socket_dir: str) -> str:
    name = f"{index:04d}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
  <data:vector name="Displacement" waveform-degree="1" />
  <data:vector name="Force" waveform-degree="1" />
  <mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement" /><use-data name="Force" /></mesh>
  <mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement" /><use-data name="Force" /></mesh>
  <m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{socket_dir}" />
  <participant name="Structure_{name}"><provide-mesh name="Structure-Mesh" /><write-data name="Displacement" mesh="Structure-Mesh" /><read-data name="Force" mesh="Structure-Mesh" /></participant>
  <participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}" /><provide-mesh name="Fluid-Mesh" /><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent" /><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative" /><write-data name="Force" mesh="Fluid-Mesh" /><read-data name="Displacement" mesh="Fluid-Mesh" /></participant>
  <coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}" /><time-window-size value="0.005" /><max-time value="0.04" /><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}" /><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}" /></coupling-scheme:parallel-explicit>
</precice-configuration>
'''


def precice_dict(index: int) -> str:
    return f'''FoamFile
{{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml";
participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}
'''


def prepare() -> list[Path]:
    if RUNTIME.exists():
        raise RuntimeError(f"refusing to reuse runtime: {RUNTIME}")
    if not SOURCE.is_dir() or not FIXTURE.is_file() or not WORKER.is_file():
        raise RuntimeError("required source/fixture/Linux worker missing")
    cases = []
    for index in range(3):
        case = RUNTIME / f"slice_{index:04d}"
        for name in ("0", "constant", "system"):
            shutil.copytree(SOURCE / name, case / name)
        control_path = case / "system" / "controlDict"
        control = control_path.read_text(encoding="utf-8")
        control = re.sub(r"endTime\s+[^;]+;", "endTime         0.04;", control)
        control = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", control)
        control_path.write_text(control, encoding="utf-8")
        socket = wsl(RUNTIME / "precice-sockets")
        (case / "precice-config.xml").write_text(config_xml(index, socket), encoding="utf-8")
        (case / "system" / "preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(case)
    LOGS.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "process").mkdir(parents=True, exist_ok=True)
    (RUNTIME / "storage").mkdir(parents=True, exist_ok=True)
    return cases


def main() -> int:
    cases = prepare()
    started = datetime.now(timezone.utc)
    (LOGS / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project = wsl(ROOT); logs = wsl(LOGS); fixture = wsl(FIXTURE); worker = wsl(WORKER)
    participant = f"{project}/tools/precice_ancf_adapter_v1/ancf_cpp_worker_three_slice_participant_v1.py"
    configs = [wsl(case / "precice-config.xml") for case in cases]
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        f"export PYTHONPATH='{project}/src:{pydeps}';",
        f"python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs}/structure_participant.json' --barrier-log '{logs}/global_barrier.jsonl' --worker '{worker}' --fixture '{fixture}' --steps 8 --dt 0.005 --run-id '{RUN_ID}' --case-id '{CASE_ID}' > '{logs}/structure.stdout' 2> '{logs}/structure.stderr' & spid=\\$!;",
        f"(cd '{wsl(cases[0])}' && pimpleFoam > '{logs}/fluid_0000.stdout' 2> '{logs}/fluid_0000.stderr') & fpid0=\\$!;",
        f"(cd '{wsl(cases[1])}' && pimpleFoam > '{logs}/fluid_0001.stdout' 2> '{logs}/fluid_0001.stderr') & fpid1=\\$!;",
        f"(cd '{wsl(cases[2])}' && pimpleFoam > '{logs}/fluid_0002.stdout' 2> '{logs}/fluid_0002.stderr') & fpid2=\\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\\$spid\" \"\\$fpid0\" \"\\$fpid1\" \"\\$fpid2\" > '{logs}/pids.txt';",
        "set +e; wait \"\\$spid\"; sr=\\$?; wait \"\\$fpid0\"; r0=\\$?; wait \"\\$fpid1\"; r1=\\$?; wait \"\\$fpid2\"; r2=\\$?; set -e;",
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
    records = structure.get("records", []); barriers = structure.get("barriers", [])
    fluid_text = [(LOGS / f"fluid_{i:04d}.stdout").read_text(encoding="utf-8", errors="replace") if (LOGS / f"fluid_{i:04d}.stdout").is_file() else "" for i in range(3)]
    fluid_err = [(LOGS / f"fluid_{i:04d}.stderr").read_text(encoding="utf-8", errors="replace") if (LOGS / f"fluid_{i:04d}.stderr").is_file() else "" for i in range(3)]
    checks = {
        "structure_finalized": structure.get("finalized") is True,
        "records_24": len(records) == 24,
        "each_slice_records_8": all(sum(r.get("slice_id") == f"slice_{i:04d}" for r in records) == 8 for i in range(3)),
        "times_005_to_040": all([round(float(r.get("time_s", -1)), 12) for r in records if r.get("slice_id") == f"slice_{i:04d}"] == [round(0.005 * j, 12) for j in range(1, 9)] for i in range(3)),
        "identity_continuous": all([r.get("sequence") for r in records if r.get("slice_id") == f"slice_{i:04d}"] == list(range(1, 9)) for i in range(3)),
        "tick_consistent": all(r.get("integer_tick") == int(round(float(r.get("time_s", -1)) * 1e9)) for r in records),
        "global_barrier_8": len(barriers) == 8 and all(b.get("committed") is True and len(b.get("slices_ready", [])) == 3 for b in barriers),
        "worker_single_start_and_close": structure.get("worker", {}).get("pid", 0) > 0 and structure.get("worker", {}).get("closed") is True and structure.get("worker", {}).get("return_code") == 0,
        "worker_projection_audited": isinstance(structure.get("projection_contract"), str),
        "fluid_end_marker": all(re.search(r"^End$", text, re.M) is not None for text in fluid_text),
        "fluid_stderr_empty": all(not text.strip() for text in fluid_err),
        "purge_write_enabled": all("purgeWrite      1;" in (case / "system" / "controlDict").read_text(encoding="utf-8") for case in cases),
    }
    gate = {
        "gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_040S_V1_GATE", "status": "pass" if run.returncode == 0 and all(checks.values()) else "do_not_pass", "timestamp": ended.isoformat(),
        "stage_id": "stage4f_d_cpp_worker_precice_three_slice_040s_v1", "run_id": RUN_ID, "case_id": CASE_ID,
        "scope_contract": {"openfoam": "10", "precice": "3.4.1", "dt_s": 0.005, "steps": 8, "end_time_s": 0.04, "slice_count": 3, "worker": "persistent Linux C++ ANCF kernel"},
        "checks": checks, "runtime": str(RUNTIME), "source_hashes": {"worker": sha(WORKER), "fixture": sha(FIXTURE), "participant": sha(ROOT / "tools" / "precice_ancf_adapter_v1" / "ancf_cpp_worker_three_slice_participant_v1.py"), "source_case_control": sha(SOURCE / "system" / "controlDict")},
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1}, "owned_residual": 0, "return_code": run.returncode,
        "wall_clock": {"start_utc": started.isoformat(), "end_utc": ended.isoformat(), "elapsed_s": (ended - started).total_seconds()},
        "protected": {"historical_evidence_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False, "formal_viv_validation_complete": False},
        "qualification": "three-slice preCICE/OpenFOAM 10 smoke using one persistent Linux C++ ANCF worker with explicit force/state projection and global barrier; not formal VIV statistics or MATLAB/C++ equivalence proof",
        "next_authorization": "new explicit authorization required before any longer three-slice segment",
    }
    out = ROOT / "results" / "293_cpp_worker_precice_three_slice_040s_v1"; out.mkdir(parents=True, exist_ok=True)
    (out / "stage4f_d_cpp_worker_precice_three_slice_040s_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "structure_participant.json").write_text(json.dumps(structure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "wall_clock_s": gate["wall_clock"]["elapsed_s"], "return_code": run.returncode}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
