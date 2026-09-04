"""Authorized Stage 303 fresh 0 -> 10 s mapping-diagnostic run."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime/stage303_interface_mapping_repair_v1_fresh_zero_to10s"
RESULTS = ROOT / "results/303_interface_mapping_repair_v1"
SOURCE_CASE = ROOT / "runtime/284_precice_single_slice_smoke_real_v1/case"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
INITIAL_STATE = ROOT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage303_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
LOGS = RUNTIME / "logs"
RUN_ID = "s303_fresh_zero_to10s_mapping_diag_v1"
CASE_ID = "c303_fresh_zero_to10s_mapping_diag_v1"
DT = 0.005
STEPS = 2000


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="{DT}"/><max-time value="{STEPS * DT}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''


def prepare() -> list[Path]:
    if RUNTIME.exists():
        raise RuntimeError(f"refusing to reuse runtime: {RUNTIME}")
    for path in (SOURCE_CASE, FIXTURE, INITIAL_STATE, WORKER, PARTICIPANT):
        if not path.exists():
            raise RuntimeError(f"required source missing: {path}")
    cases: list[Path] = []
    for index in range(3):
        case = RUNTIME / f"slice_{index:04d}"
        for name in ("0", "constant", "system"):
            shutil.copytree(SOURCE_CASE / name, case / name)
        control = case / "system/controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"startFrom\s+[^;]+;", "startFrom       startTime;", text)
        text = re.sub(r"startTime\s+[^;]+;", "startTime       0;", text)
        text = re.sub(r"endTime\s+[^;]+;", f"endTime         {STEPS * DT:g};", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        control.write_text(text, encoding="utf-8")
        (case / "precice-config.xml").write_text(config_xml(index, wsl(RUNTIME / "precice-sockets")), encoding="utf-8")
        (case / "system/preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(case)
    LOGS.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "process").mkdir(parents=True, exist_ok=True)
    (RUNTIME / "storage").mkdir(parents=True, exist_ok=True)
    return cases


def main() -> int:
    cases = prepare()
    started = datetime.now(timezone.utc)
    (LOGS / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project, logs, fixture, initial, worker, participant = map(wsl, (ROOT, LOGS, FIXTURE, INITIAL_STATE, WORKER, PARTICIPANT))
    configs = [wsl(case / "precice-config.xml") for case in cases]
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        f"export PYTHONPATH='{project}/src:{pydeps}';",
        f"python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs}/structure_participant.json' --barrier-log '{logs}/global_barrier.json' --checkpoint-log '{logs}/checkpoint.jsonl' --convergence-log '{logs}/convergence_summary.json' --diagnostic-log '{logs}/mapping_diagnostics.jsonl' --worker '{worker}' --fixture '{fixture}' --initial-state '{initial}' --source-step 0 --source-time 0 --steps {STEPS} --dt {DT} --run-id '{RUN_ID}' --case-id '{CASE_ID}' > '{logs}/structure.stdout' 2> '{logs}/structure.stderr' & spid=\$!;",
        f"(cd '{wsl(cases[0])}' && pimpleFoam > '{logs}/fluid_0000.stdout' 2> '{logs}/fluid_0000.stderr') & fpid0=\$!;",
        f"(cd '{wsl(cases[1])}' && pimpleFoam > '{logs}/fluid_0001.stdout' 2> '{logs}/fluid_0001.stderr') & fpid1=\$!;",
        f"(cd '{wsl(cases[2])}' && pimpleFoam > '{logs}/fluid_0002.stdout' 2> '{logs}/fluid_0002.stderr') & fpid2=\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\$spid\" \"\$fpid0\" \"\$fpid1\" \"\$fpid2\" > '{logs}/pids.txt';",
        "set +e; wait \"\$spid\"; sr=\$?; wait \"\$fpid0\"; r0=\$?; wait \"\$fpid1\"; r1=\$?; wait \"\$fpid2\"; r2=\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\$sr\" \"\$r0\" \"\$r1\" \"\$r2\" > '{logs}/returns.txt';",
        "if [ \"\$sr\" -ne 0 ] || [ \"\$r0\" -ne 0 ] || [ \"\$r1\" -ne 0 ] || [ \"\$r2\" -ne 0 ]; then exit 1; fi",
    ])
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (LOGS / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (LOGS / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (LOGS / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    structure = json.loads((LOGS / "structure_participant.json").read_text(encoding="utf-8")) if (LOGS / "structure_participant.json").is_file() else {}
    returns = (LOGS / "returns.txt").read_text(encoding="utf-8", errors="replace") if (LOGS / "returns.txt").is_file() else ""
    diagnostics = [json.loads(line) for line in (LOGS / "mapping_diagnostics.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()] if (LOGS / "mapping_diagnostics.jsonl").is_file() else []
    fluids = [(LOGS / f"fluid_{index:04d}.stdout").read_text(encoding="utf-8", errors="replace") if (LOGS / f"fluid_{index:04d}.stdout").is_file() else "" for index in range(3)]
    errors = [(LOGS / f"fluid_{index:04d}.stderr").read_text(encoding="utf-8", errors="replace") if (LOGS / f"fluid_{index:04d}.stderr").is_file() else "" for index in range(3)]
    checks = {
        "fresh_source_step_zero": structure.get("source_global_step") == 0 and structure.get("source_time_s") == 0.0,
        "finalized": structure.get("finalized") is True,
        "committed_2000": structure.get("target_global_step") == STEPS and structure.get("local_committed_steps") == STEPS,
        "slice_counts_2000": all(structure.get("slice_counts", {}).get(f"slice_{index:04d}") == STEPS for index in range(3)),
        "mapping_diagnostics_2000": len(diagnostics) == STEPS,
        "mapping_errors_finite": all(math.isfinite(float(row[key])) for row in diagnostics for key in ("virtual_work_error", "force_balance_error", "moment_balance_error")),
        "worker_closed_zero": structure.get("worker", {}).get("closed") is True and structure.get("worker", {}).get("return_code") == 0,
        "fluid_end": all(re.search(r"^End$", text, re.M) is not None for text in fluids),
        "fluid_stderr_empty": all(not text.strip() for text in errors),
        "returns_zero": all(re.search(rf"{name}=0", returns) for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "purge_write": all("purgeWrite      1;" in (case / "system/controlDict").read_text(encoding="utf-8") for case in cases),
    }
    gate = {
        "gate_id": "STAGE4F_D_INTERFACE_MAPPING_REPAIR_V1_FRESH_ZERO_TO10S_GATE",
        "status": "pass" if run.returncode == 0 and all(checks.values()) else "do_not_pass",
        "stage_id": "stage4f_d_interface_mapping_repair_v1_fresh_zero_to10s",
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "scope_contract": {"source_step": 0, "source_time_s": 0.0, "target_step": STEPS, "target_time_s": STEPS * DT, "dt_s": DT, "slice_count": 3, "storage": "rolling fields + scalar mapping diagnostics"},
        "checks": checks,
        "diagnostic_summary": {"count": len(diagnostics), "max_virtual_work_error": max((float(row["virtual_work_error"]) for row in diagnostics), default=None), "max_force_balance_error": max((float(row["force_balance_error"]) for row in diagnostics), default=None), "max_moment_balance_error": max((float(row["moment_balance_error"]) for row in diagnostics), default=None)},
        "runtime": str(RUNTIME),
        "source_hashes": {"worker": sha(WORKER), "fixture": sha(FIXTURE), "initial_state": sha(INITIAL_STATE), "participant": sha(PARTICIPANT)},
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "return_code": run.returncode,
        "wall_clock": {"start_utc": started.isoformat(), "end_utc": ended.isoformat(), "elapsed_s": (ended - started).total_seconds()},
        "protected": {"stage302_runtime_modified": False, "historical_evidence_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False},
        "qualification": "fresh 0-10 s interface mapping/virtual-work diagnostic; not formal 15-cycle VIV convergence",
        "next_authorization": "new explicit authorization required before longer physical run",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_interface_mapping_repair_v1_fresh_zero_to10s_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "wall_clock_s": gate["wall_clock"]["elapsed_s"], "diagnostic_summary": gate["diagnostic_summary"]}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
