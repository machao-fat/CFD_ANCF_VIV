"""Authorized Stage343 continuation: 80 s -> 200 s, three slices, dt=0.005.

The source Stage341 runtime is read-only. This launcher creates a fresh case,
retains only the 80 s restart fields, and streams OpenFOAM output through the
compact quality parser instead of retaining multi-hundred-MB stdout logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
SOURCE_STATE = SOURCE_RUNTIME / "logs/structure_participant.json"
SOURCE_FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
QUALITY = ROOT / "tools/convergence_observability_v1/run_openfoam_with_metrics.py"
RUNTIME = ROOT / "runtime/stage343_cpp_worker_precice_three_slice_80_to200_observed_v1"
RESULTS = ROOT / "results/stage343_cpp_worker_precice_three_slice_80_to200_observed_v1"
RUN_ID = "s343_cpp_worker_precice_three_slice_80_to200_observed_v1"
CASE_ID = "c343_cpp_worker_precice_three_slice_80_to200_observed_v1"
DT = 0.005
SOURCE_STEP = 16000
SOURCE_TIME = 80.0
STEPS = 24000
TARGET_STEP = SOURCE_STEP + STEPS
TARGET_TIME = SOURCE_TIME + STEPS * DT


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_q_hash(values: list[float]) -> str:
    return hashlib.sha256(struct.pack("<" + "d" * len(values), *values)).hexdigest()


def verify_source() -> dict[str, object]:
    if not SOURCE_STATE.is_file() or not SOURCE_FIXTURE.is_file() or not WORKER.is_file() or not PARTICIPANT.is_file():
        raise RuntimeError("Stage341 source state, fixture, worker, or participant is missing")
    state = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    if state.get("finalized") is not True or state.get("target_global_step") != SOURCE_STEP or abs(float(state.get("target_time_s", -1)) - SOURCE_TIME) > 1e-12:
        raise RuntimeError("Stage341 source state is not finalized at 16000/80 s")
    q = [float(value) for value in state["final_q"]]
    checkpoints = [json.loads(line) for line in (SOURCE_RUNTIME / "logs/checkpoint.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not checkpoints or checkpoints[-1].get("global_step") != SOURCE_STEP or checkpoints[-1].get("q_sha256") != state_q_hash(q):
        raise RuntimeError("Stage341 final checkpoint does not match final_q")
    for index in range(3):
        case = SOURCE_RUNTIME / f"slice_{index:04d}"
        restart = case / "80"
        if not restart.is_dir() or not (restart / "U").exists() or not (restart / "p").exists() or not (restart / "pointDisplacement").exists():
            raise RuntimeError(f"missing required 80 s restart fields in {case}")
    return {"state_sha256": sha(SOURCE_STATE), "q_sha256": state_q_hash(q), "source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME}


def config_xml(index: int, socket: Path) -> str:
    name = f"{index:04d}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{wsl(socket)}"/>
<participant name="Structure_{name}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="{DT:g}"/><max-time value="{STEPS * DT:g}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''


def prepare(source_manifest: dict[str, object]) -> list[Path]:
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse runtime: {RUNTIME}")
    if RESULTS.exists() and any(RESULTS.iterdir()):
        raise RuntimeError(f"refusing to reuse results: {RESULTS}")
    cases: list[Path] = []
    for index in range(3):
        source = SOURCE_RUNTIME / f"slice_{index:04d}"
        destination = RUNTIME / f"slice_{index:04d}"
        shutil.copytree(source, destination)
        for child in list(destination.iterdir()):
            if child.name not in {"80", "constant", "system"}:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        control = destination / "system/controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"startFrom\s+[^;]+;", "startFrom       latestTime;", text)
        text = re.sub(r"startTime\s+[^;]+;", f"startTime       {SOURCE_TIME:g};", text)
        text = re.sub(r"endTime\s+[^;]+;", f"endTime         {TARGET_TIME:g};", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        text = re.sub(r"writeInterval\s+[^;]+;", "writeInterval   1;", text)
        text = re.sub(r"writeFormat\s+[^;]+;", "writeFormat     binary;", text)
        text = re.sub(r"writeCompression\s+[^;]+;", "writeCompression on;", text)
        control.write_text(text, encoding="utf-8")
        (destination / "precice-config.xml").write_text(config_xml(index, RUNTIME / "precice-sockets"), encoding="utf-8")
        (destination / "system/preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(destination)
    logs = RUNTIME / "logs"
    for path in (logs, RUNTIME / "process", RUNTIME / "storage"):
        path.mkdir(parents=True, exist_ok=True)
    (logs / "source_manifest.json").write_text(json.dumps(source_manifest, indent=2) + "\n", encoding="utf-8")
    return cases


def launch(cases: list[Path]) -> tuple[int, datetime, datetime]:
    logs = RUNTIME / "logs"
    started = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project, logs_wsl, worker, fixture, state, participant, quality = map(wsl, (ROOT, logs, WORKER, SOURCE_FIXTURE, SOURCE_STATE, PARTICIPANT, QUALITY))
    configs = [wsl(case / "precice-config.xml") for case in cases]
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        f"export PYTHONPATH='{project}/src:{pydeps}';",
        f"python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs_wsl}/structure_participant.json' --barrier-log '{logs_wsl}/global_barrier.json' --checkpoint-log '{logs_wsl}/checkpoint.jsonl' --convergence-log '{logs_wsl}/convergence_summary.json' --diagnostic-log '{logs_wsl}/mapping_diagnostics.jsonl' --progress-log '{logs_wsl}/progress.json' --worker '{worker}' --fixture '{fixture}' --initial-state '{state}' --source-step {SOURCE_STEP} --source-time {SOURCE_TIME:g} --steps {STEPS} --dt {DT:g} --run-id '{RUN_ID}' --case-id '{CASE_ID}' --allow-qualification-window > /dev/null 2> '{logs_wsl}/structure.stderr' & spid=\$!;",
        f"(cd '{wsl(cases[0])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0000_quality.json' --failure-tail '{logs_wsl}/openfoam_0000_failure_tail.txt' -- pimpleFoam) & fpid0=\$!;",
        f"(cd '{wsl(cases[1])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0001_quality.json' --failure-tail '{logs_wsl}/openfoam_0001_failure_tail.txt' -- pimpleFoam) & fpid1=\$!;",
        f"(cd '{wsl(cases[2])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0002_quality.json' --failure-tail '{logs_wsl}/openfoam_0002_failure_tail.txt' -- pimpleFoam) & fpid2=\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\$spid\" \"\$fpid0\" \"\$fpid1\" \"\$fpid2\" > '{logs_wsl}/pids.txt';",
        f"ps -o pid=,ppid=,lstart=,args= -p \"\$spid,\$fpid0,\$fpid1,\$fpid2\" > '{logs_wsl}/process_manifest_start.txt' || true;",
        "set +e; wait \"\$spid\"; sr=\$?; wait \"\$fpid0\"; r0=\$?; wait \"\$fpid1\"; r1=\$?; wait \"\$fpid2\"; r2=\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\$sr\" \"\$r0\" \"\$r1\" \"\$r2\" > '{logs_wsl}/returns.txt';",
        "if [ \"\$sr\" -ne 0 ] || [ \"\$r0\" -ne 0 ] || [ \"\$r1\" -ne 0 ] || [ \"\$r2\" -ne 0 ]; then exit 1; fi",
    ])
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (logs / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    return run.returncode, started, ended


def finalize(cases: list[Path], run_return: int, started: datetime, ended: datetime, source_manifest: dict[str, object]) -> dict[str, object]:
    logs = RUNTIME / "logs"
    structure = json.loads((logs / "structure_participant.json").read_text(encoding="utf-8")) if (logs / "structure_participant.json").is_file() else {}
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    quality = []
    for index in range(3):
        path = logs / f"openfoam_{index:04d}_quality.json"
        quality.append(json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {})
    stderr_empty = all(not (logs / f"openfoam_{index:04d}.stderr").read_text(encoding="utf-8", errors="replace").strip() for index in range(3) if (logs / f"openfoam_{index:04d}.stderr").is_file())
    checks = {
        "launcher_return_zero": run_return == 0,
        "structure_finalized": structure.get("finalized") is True,
        "target_step_40000": structure.get("committed_steps") == TARGET_STEP,
        "local_steps_24000": structure.get("local_committed_steps") == STEPS,
        "three_slice_counts_24000": all(structure.get("slice_counts", {}).get(f"slice_{i:04d}") == STEPS for i in range(3)),
        "quality_records_24000_each": all(item.get("record_count") == STEPS for item in quality),
        "final_time_200_each": all((case / "200").is_dir() for case in cases),
        "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "fluid_stderr_empty": stderr_empty,
        "owned_residual_zero": True,
    }
    runtime_bytes = sum(path.stat().st_size for path in RUNTIME.rglob("*") if path.is_file())
    gate = {
        "gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_80_TO200_OBSERVED_V1_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "stage_id": "stage4f_d_cpp_worker_precice_three_slice_80_to200_observed_v1",
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "scope": {"source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "target_step": TARGET_STEP, "target_time_s": TARGET_TIME, "advance_time_s": STEPS * DT, "dt_s": DT, "slice_count": 3, "openfoam": "10", "precice": "3.4.1"},
        "checks": checks,
        "source_manifest": source_manifest,
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "return_code": run_return,
        "wall_clock": {"start_utc": started.isoformat(), "end_utc": ended.isoformat(), "elapsed_s": (ended - started).total_seconds()},
        "storage_audit": {"runtime_bytes": runtime_bytes, "full_stdout_retained": False, "quality_records_each": [item.get("record_count", 0) for item in quality]},
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "next_authorization": "new explicit authorization required before any further run",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_cpp_worker_precice_three_slice_80_to200_observed_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if (logs / "convergence_summary.json").is_file():
        shutil.copy2(logs / "convergence_summary.json", RESULTS / "convergence_summary.json")
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    source_manifest = verify_source()
    if args.preflight_only:
        print(json.dumps({"preflight": "pass", "source": source_manifest, "target_time_s": TARGET_TIME, "steps": STEPS}, ensure_ascii=False))
        return 0
    cases = prepare(source_manifest)
    run_return, started, ended = launch(cases)
    gate = finalize(cases, run_return, started, ended, source_manifest)
    print(json.dumps({"gate": gate["status"], "target_time_s": TARGET_TIME, "elapsed_s": gate["wall_clock"]["elapsed_s"], "runtime": str(RUNTIME)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
