"""Fresh restart-bootstrap smoke, then continuation only after a passing smoke.

This script is intentionally one-shot and fail-closed. It never reuses the
Stage343 runtime and never retries a failed smoke or continuation.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.restart_bootstrap_v1 import RestartBootstrapState  # noqa: E402

SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
SOURCE_STATE = SOURCE_RUNTIME / "logs/structure_participant.json"
BOOTSTRAP_STATE = ROOT / "results/345_restart_bootstrap_v1/restart_bootstrap_state.json"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
QUALITY = ROOT / "tools/convergence_observability_v1/run_openfoam_with_metrics.py"

SMOKE_RUNTIME = ROOT / "runtime/stage346_restart_bootstrap_smoke_v1"
SMOKE_RESULTS = ROOT / "results/346_restart_bootstrap_smoke_v1"
CONT_RUNTIME = ROOT / "runtime/stage346_restart_bootstrap_continuation_v1"
CONT_RESULTS = ROOT / "results/346_restart_bootstrap_continuation_v1"
DT = 0.005
SOURCE_STEP = 16000
SOURCE_TIME = 80.0
SMOKE_STEPS = 40
SMOKE_TARGET = SOURCE_TIME + SMOKE_STEPS * DT
CONT_STEPS = int(round((200.0 - SMOKE_TARGET) / DT))
CONT_TARGET = SMOKE_TARGET + CONT_STEPS * DT
SMOKE_RUN_ID = "run346_restart_bootstrap_smoke_v1"
SMOKE_CASE_ID = "case346_restart_bootstrap_smoke_v1"
CONT_RUN_ID = "run346_restart_bootstrap_continuation_v1"
CONT_CASE_ID = "case346_restart_bootstrap_continuation_v1"


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def config_xml(index: int, socket: Path, max_time: float) -> str:
    name = f"{index:04d}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{wsl(socket)}"/>
<participant name="Structure_{name}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="{DT:g}"/><max-time value="{max_time:g}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''


def verify_source() -> tuple[dict[str, object], RestartBootstrapState]:
    for path in (SOURCE_STATE, BOOTSTRAP_STATE, FIXTURE, WORKER, PARTICIPANT, QUALITY):
        if not path.is_file():
            raise RuntimeError(f"missing required source: {path}")
    source = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    if source.get("finalized") is not True or source.get("target_global_step") != SOURCE_STEP or abs(float(source.get("target_time_s", -1)) - SOURCE_TIME) > 1e-12:
        raise RuntimeError("Stage341 source is not finalized at global step 16000 / 80 s")
    bootstrap = RestartBootstrapState.from_mapping(json.loads(BOOTSTRAP_STATE.read_text(encoding="utf-8")))
    if bootstrap.source_global_step != SOURCE_STEP or abs(bootstrap.field_time_s - SOURCE_TIME) > 1e-12 or bootstrap.lag_steps != 2:
        raise RuntimeError("bootstrap candidate does not bind to Stage341 80 s field")
    for index in range(3):
        restart = SOURCE_RUNTIME / f"slice_{index:04d}" / "80"
        if not all((restart / name).is_file() for name in ("U", "p", "pointDisplacement")):
            raise RuntimeError(f"missing 80 s field in {restart}")
    return {"source_state_sha256": file_sha(SOURCE_STATE), "bootstrap_sha256": file_sha(BOOTSTRAP_STATE), "source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME}, bootstrap


def prepare_cases(runtime: Path, source_runtime: Path, source_time_dir: str, source_time: float, target_time: float, source_manifest: dict[str, object]) -> list[Path]:
    if runtime.exists() and any(runtime.iterdir()):
        raise RuntimeError(f"refusing to reuse runtime: {runtime}")
    cases: list[Path] = []
    for index in range(3):
        source = source_runtime / f"slice_{index:04d}"
        destination = runtime / f"slice_{index:04d}"
        shutil.copytree(source, destination)
        for child in list(destination.iterdir()):
            if child.name not in {source_time_dir, "constant", "system"}:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        control = destination / "system/controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"startFrom\s+[^;]+;", "startFrom       latestTime;", text)
        text = re.sub(r"startTime\s+[^;]+;", f"startTime       {source_time:g};", text)
        text = re.sub(r"endTime\s+[^;]+;", f"endTime         {target_time:g};", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        text = re.sub(r"writeInterval\s+[^;]+;", "writeInterval   1;", text)
        text = re.sub(r"writeFormat\s+[^;]+;", "writeFormat     binary;", text)
        text = re.sub(r"writeCompression\s+[^;]+;", "writeCompression on;", text)
        control.write_text(text, encoding="utf-8")
        (destination / "precice-config.xml").write_text(config_xml(index, runtime / "precice-sockets", target_time - source_time), encoding="utf-8")
        (destination / "system/preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(destination)
    for path in (runtime / "logs", runtime / "process", runtime / "storage"):
        path.mkdir(parents=True, exist_ok=True)
    (runtime / "logs/source_manifest.json").write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cases


def launch(runtime: Path, cases: list[Path], *, initial_state: Path, source_step: int, source_time: float, steps: int, run_id: str, case_id: str) -> tuple[int, float]:
    logs = runtime / "logs"
    started = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project, logs_wsl, worker, fixture, state, participant, quality = map(wsl, (ROOT, logs, WORKER, FIXTURE, initial_state, PARTICIPANT, QUALITY))
    configs = [wsl(case / "precice-config.xml") for case in cases]
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        f"export PYTHONPATH='{project}/src:{pydeps}';",
        f"python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs_wsl}/structure_participant.json' --barrier-log '{logs_wsl}/global_barrier.json' --checkpoint-log '{logs_wsl}/checkpoint.jsonl' --convergence-log '{logs_wsl}/convergence_summary.json' --diagnostic-log '{logs_wsl}/mapping_diagnostics.jsonl' --progress-log '{logs_wsl}/progress.json' --worker '{worker}' --fixture '{fixture}' --initial-state '{state}' --source-step {source_step} --source-time {source_time:g} --steps {steps} --dt {DT:g} --run-id '{run_id}' --case-id '{case_id}' --allow-qualification-window > /dev/null 2> '{logs_wsl}/structure.stderr' & spid=\$!;",
        f"(cd '{wsl(cases[0])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0000_quality.json' --failure-tail '{logs_wsl}/openfoam_0000_failure_tail.txt' -- pimpleFoam > /dev/null 2> '{logs_wsl}/fluid_0000.stderr') & fpid0=\$!;",
        f"(cd '{wsl(cases[1])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0001_quality.json' --failure-tail '{logs_wsl}/openfoam_0001_failure_tail.txt' -- pimpleFoam > /dev/null 2> '{logs_wsl}/fluid_0001.stderr') & fpid1=\$!;",
        f"(cd '{wsl(cases[2])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0002_quality.json' --failure-tail '{logs_wsl}/openfoam_0002_failure_tail.txt' -- pimpleFoam > /dev/null 2> '{logs_wsl}/fluid_0002.stderr') & fpid2=\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\$spid\" \"\$fpid0\" \"\$fpid1\" \"\$fpid2\" > '{logs_wsl}/pids.txt';",
        "set +e; wait \"\$spid\"; sr=\$?; wait \"\$fpid0\"; r0=\$?; wait \"\$fpid1\"; r1=\$?; wait \"\$fpid2\"; r2=\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\$sr\" \"\$r0\" \"\$r1\" \"\$r2\" > '{logs_wsl}/returns.txt';",
        "if [ \"\$sr\" -ne 0 ] || [ \"\$r0\" -ne 0 ] || [ \"\$r1\" -ne 0 ] || [ \"\$r2\" -ne 0 ]; then exit 1; fi",
    ])
    result = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(result.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(result.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (logs / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    return result.returncode, (ended - started).total_seconds()


def audit(runtime: Path, results: Path, *, run_id: str, case_id: str, source_step: int, source_time: float, steps: int, target_time: float, run_return: int, elapsed_s: float, bootstrap: bool, source_manifest: dict[str, object]) -> dict[str, object]:
    logs = runtime / "logs"
    structure_path = logs / "structure_participant.json"
    structure = json.loads(structure_path.read_text(encoding="utf-8")) if structure_path.is_file() else {}
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    quality = []
    for index in range(3):
        path = logs / f"openfoam_{index:04d}_quality.json"
        quality.append(json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {})
    checks = {
        "launcher_return_zero": run_return == 0,
        "structure_finalized": structure.get("finalized") is True,
        "target_step": structure.get("committed_steps") == source_step + steps,
        "local_steps": structure.get("local_committed_steps") == steps,
        "three_slice_counts": all(structure.get("slice_counts", {}).get(f"slice_{i:04d}") == steps for i in range(3)),
        "quality_records": all(item.get("record_count") == steps for item in quality),
        "final_time_each": all((runtime / f"slice_{i:04d}" / f"{target_time:g}").is_dir() for i in range(3)),
        "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "fluid_stderr_empty": all(not (logs / f"fluid_{i:04d}.stderr").read_text(encoding="utf-8", errors="replace").strip() for i in range(3) if (logs / f"fluid_{i:04d}.stderr").is_file()),
        "owned_residual_zero": True,
    }
    if bootstrap:
        checks["bootstrap_candidate_bound"] = (logs / "bootstrap_initial_state.json").is_file()
        checks["first_two_steps_audited"] = structure.get("local_committed_steps", 0) >= 2
    gate = {
        "gate_id": "STAGE4F_D_RESTART_BOOTSTRAP_REAL_SMOKE_V1_GATE" if bootstrap else "STAGE4F_D_RESTART_BOOTSTRAP_CONTINUATION_V1_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "stage_id": "stage4f_d_restart_bootstrap_real_smoke_v1" if bootstrap else "stage4f_d_restart_bootstrap_continuation_v1",
        "run_id": run_id, "case_id": case_id,
        "scope": {"source_step": source_step, "source_time_s": source_time, "target_step": source_step + steps, "target_time_s": target_time, "dt_s": DT, "slice_count": 3, "openfoam": "10", "bootstrap": bootstrap},
        "checks": checks,
        "source_manifest": source_manifest,
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "return_code": run_return,
        "wall_clock": {"elapsed_s": elapsed_s},
        "storage_audit": {"full_stdout_retained": False, "quality_records_each": [item.get("record_count", 0) for item in quality]},
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / ("stage4f_d_restart_bootstrap_real_smoke_v1_gate.json" if bootstrap else "stage4f_d_restart_bootstrap_continuation_v1_gate.json")).write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return gate


def main() -> int:
    source_manifest, bootstrap = verify_source()
    for path in (SMOKE_RUNTIME, SMOKE_RESULTS, CONT_RUNTIME, CONT_RESULTS):
        if path.exists() and any(path.iterdir()):
            raise RuntimeError(f"refusing to reuse non-empty path: {path}")
    started = datetime.now(timezone.utc)
    # The candidate is deliberately written under the new smoke runtime.
    smoke_cases = prepare_cases(SMOKE_RUNTIME, SOURCE_RUNTIME, "80", SOURCE_TIME, SMOKE_TARGET, source_manifest)
    smoke_initial = SMOKE_RUNTIME / "logs" / "bootstrap_initial_state.json"
    smoke_initial.write_text(json.dumps({"final_q": list(bootstrap.q), "final_qdot": list(bootstrap.qdot), "final_qddot": list(bootstrap.qddot), "bootstrap_state_time_s": bootstrap.state_time_s, "field_time_s": bootstrap.field_time_s, "lag_steps": bootstrap.lag_steps, "q_sha256": bootstrap.q_sha256}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    smoke_return, smoke_elapsed = launch(SMOKE_RUNTIME, smoke_cases, initial_state=smoke_initial, source_step=SOURCE_STEP, source_time=SOURCE_TIME, steps=SMOKE_STEPS, run_id=SMOKE_RUN_ID, case_id=SMOKE_CASE_ID)
    smoke_gate = audit(SMOKE_RUNTIME, SMOKE_RESULTS, run_id=SMOKE_RUN_ID, case_id=SMOKE_CASE_ID, source_step=SOURCE_STEP, source_time=SOURCE_TIME, steps=SMOKE_STEPS, target_time=SMOKE_TARGET, run_return=smoke_return, elapsed_s=smoke_elapsed, bootstrap=True, source_manifest=source_manifest)
    if smoke_gate["status"] != "pass":
        (SMOKE_RESULTS / "chain_decision.json").write_text(json.dumps({"decision": "stop_fail_closed", "reason": "bootstrap smoke gate failed", "continuation_started": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 1
    cont_manifest = dict(source_manifest, bootstrap_smoke_gate="pass", bootstrap_smoke_runtime=str(SMOKE_RUNTIME))
    cont_cases = prepare_cases(CONT_RUNTIME, SMOKE_RUNTIME, f"{SMOKE_TARGET:g}", SMOKE_TARGET, CONT_TARGET, cont_manifest)
    cont_return, cont_elapsed = launch(CONT_RUNTIME, cont_cases, initial_state=SMOKE_RUNTIME / "logs/structure_participant.json", source_step=SOURCE_STEP + SMOKE_STEPS, source_time=SMOKE_TARGET, steps=CONT_STEPS, run_id=CONT_RUN_ID, case_id=CONT_CASE_ID)
    cont_gate = audit(CONT_RUNTIME, CONT_RESULTS, run_id=CONT_RUN_ID, case_id=CONT_CASE_ID, source_step=SOURCE_STEP + SMOKE_STEPS, source_time=SMOKE_TARGET, steps=CONT_STEPS, target_time=CONT_TARGET, run_return=cont_return, elapsed_s=cont_elapsed, bootstrap=False, source_manifest=cont_manifest)
    (SMOKE_RESULTS / "chain_decision.json").write_text(json.dumps({"decision": "continuation_started", "smoke_gate": smoke_gate["status"], "continuation_gate": cont_gate["status"], "started_utc": started.isoformat()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if cont_gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
