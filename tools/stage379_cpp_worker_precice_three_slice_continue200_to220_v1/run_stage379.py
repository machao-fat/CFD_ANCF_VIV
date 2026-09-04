"""Authorized three-slice continuation from the validated 200 s endpoint."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.convergence_observability_v3 import audit_quality_records  # noqa: E402

SOURCE = ROOT / "runtime/stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3"
SOURCE_STATE = SOURCE / "logs/structure_participant.json"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
QUALITY = ROOT / "tools/stage376_cpp_worker_precice_three_slice_observability_040s_v1/run_openfoam_with_metrics_v2.py"
RUNTIME = ROOT / "runtime/stage379_cpp_worker_precice_three_slice_continue200_to220_v1"
RESULTS = ROOT / "results/stage379_cpp_worker_precice_three_slice_continue200_to220_v1"
STAGE_ID = "stage4f_d_cpp_worker_precice_three_slice_continue200_to220_v1"
RUN_ID = "run379_cpp_worker_precice_three_slice_continue200_to220_v1"
CASE_ID = "case379_cpp_worker_precice_three_slice_continue200_to220_v1"
DT = 0.005
SOURCE_STEP = 40000
SOURCE_TIME = 200.0
STEPS = 4000
TARGET_STEP = SOURCE_STEP + STEPS
TARGET_TIME = SOURCE_TIME + STEPS * DT


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def config_xml(index: int) -> str:
    name = f"{index:04d}"
    socket = wsl(RUNTIME / "precice-sockets")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{socket}"/>
<participant name="Structure_{name}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="{DT:g}"/><max-time value="{STEPS * DT:g}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''


def verify_source() -> dict[str, object]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse Stage 379 paths")
    for path in (SOURCE_STATE, FIXTURE, WORKER, PARTICIPANT, QUALITY):
        if not path.is_file():
            raise RuntimeError(f"missing required source: {path}")
    state = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    if state.get("finalized") is not True or state.get("committed_steps") != SOURCE_STEP or state.get("local_committed_steps") != 23960:
        raise RuntimeError("source is not the finalized 200 s endpoint")
    if abs(float(state.get("target_time_s", -1)) - SOURCE_TIME) > 1e-12:
        raise RuntimeError("source time is not 200 s")
    expected = {f"slice_{i:04d}": 23960 for i in range(3)}
    if state.get("slice_counts") != expected:
        raise RuntimeError("source slice counts are not synchronized at 23960")
    fields = ("U", "p", "pointDisplacement", "cellDisplacement", "phi", "meshPhi", "Uf", "Force")
    for index in range(3):
        restart = SOURCE / f"slice_{index:04d}/{SOURCE_TIME:g}"
        for name in fields:
            if not (restart / name).is_file():
                raise RuntimeError(f"missing source field: {restart / name}")
    return {"source_runtime": str(SOURCE), "source_state_sha256": sha(SOURCE_STATE), "source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "source_fields": list(fields), "source_read_only": True}


def prepare(source_manifest: dict[str, object]) -> list[Path]:
    cases: list[Path] = []
    for index in range(3):
        source_case = SOURCE / f"slice_{index:04d}"
        case = RUNTIME / f"slice_{index:04d}"
        case.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source_case / f"{SOURCE_TIME:g}", case / f"{SOURCE_TIME:g}")
        shutil.copytree(source_case / "constant", case / "constant")
        shutil.copytree(source_case / "system", case / "system")
        control = case / "system/controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"startFrom\s+[^;]+;", "startFrom       latestTime;", text)
        text = re.sub(r"startTime\s+[^;]+;", f"startTime       {SOURCE_TIME:g};", text)
        text = re.sub(r"endTime\s+[^;]+;", f"endTime         {TARGET_TIME:g};", text)
        text = re.sub(r"deltaT\s+[^;]+;", f"deltaT          {DT:g};", text)
        text = re.sub(r"writeInterval\s+[^;]+;", "writeInterval   1;", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        text = re.sub(r"writeFormat\s+[^;]+;", "writeFormat     binary;", text)
        text = re.sub(r"writeCompression\s+[^;]+;", "writeCompression on;", text)
        control.write_text(text, encoding="utf-8")
        (case / "precice-config.xml").write_text(config_xml(index), encoding="utf-8")
        (case / "system/preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(case)
    for path in (RUNTIME / "logs", RUNTIME / "process", RUNTIME / "storage", RUNTIME / "precice-sockets"):
        path.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "logs/preflight.json").write_text(json.dumps({"schema_version": 1, "stage_id": STAGE_ID, "status": "pass", "source_manifest": source_manifest, "target_step": TARGET_STEP, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": 3, "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0}, "owned_residual": 0, "storage_policy": {"purgeWrite": 1, "writeFormat": "binary", "retained": "latest field plus compact logs/checkpoints"}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cases


def launch(cases: list[Path]) -> tuple[int, float]:
    logs = RUNTIME / "logs"
    start = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(start.isoformat() + "\n", encoding="utf-8")
    project, logs_wsl = wsl(ROOT), wsl(logs)
    configs = [wsl(case / "precice-config.xml") for case in cases]
    worker, fixture, state, participant, quality = map(wsl, (WORKER, FIXTURE, SOURCE_STATE, PARTICIPANT, QUALITY))
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = f'''export ZSH_NAME=
source /opt/openfoam10/etc/bashrc
set -u
export PYTHONPATH='{project}/src:{pydeps}'
python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs_wsl}/structure_participant.json' --barrier-log '{logs_wsl}/global_barrier.json' --checkpoint-log '{logs_wsl}/checkpoint.jsonl' --diagnostic-log '{logs_wsl}/mapping_diagnostics.jsonl' --progress-log '{logs_wsl}/progress.json' --worker '{worker}' --fixture '{fixture}' --initial-state '{state}' --source-step {SOURCE_STEP} --source-time {SOURCE_TIME:g} --steps {STEPS} --dt {DT:g} --run-id '{RUN_ID}' --case-id '{CASE_ID}' --allow-qualification-window > /dev/null 2> '{logs_wsl}/structure.stderr' & spid=\$!
(cd '{wsl(cases[0])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0000_quality.json' --failure-tail '{logs_wsl}/openfoam_0000_failure_tail.txt' -- pimpleFoam > /dev/null 2> '{logs_wsl}/fluid_0000.stderr') & fpid0=\$!
(cd '{wsl(cases[1])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0001_quality.json' --failure-tail '{logs_wsl}/openfoam_0001_failure_tail.txt' -- pimpleFoam > /dev/null 2> '{logs_wsl}/fluid_0001.stderr') & fpid1=\$!
(cd '{wsl(cases[2])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0002_quality.json' --failure-tail '{logs_wsl}/openfoam_0002_failure_tail.txt' -- pimpleFoam > /dev/null 2> '{logs_wsl}/fluid_0002.stderr') & fpid2=\$!
printf 'structure_pid=%s\nfluid_0000_pid=%s\nfluid_0001_pid=%s\nfluid_0002_pid=%s\n' "\$spid" "\$fpid0" "\$fpid1" "\$fpid2" > '{logs_wsl}/pids.txt'
set +e
wait "\$spid"; sr=\$?
if [ "\$sr" -ne 0 ]; then kill "\$fpid0" "\$fpid1" "\$fpid2" 2>/dev/null || true; fi
wait "\$fpid0"; r0=\$?
wait "\$fpid1"; r1=\$?
wait "\$fpid2"; r2=\$?
set -e
printf 'structure_return=%s\nfluid_0000_return=%s\nfluid_0001_return=%s\nfluid_0002_return=%s\n' "\$sr" "\$r0" "\$r1" "\$r2" > '{logs_wsl}/returns.txt'
if [ "\$sr" -ne 0 ] || [ "\$r0" -ne 0 ] || [ "\$r1" -ne 0 ] || [ "\$r2" -ne 0 ]; then exit 1; fi
'''
    (logs / "launcher.sh").write_text(shell, encoding="utf-8")
    result = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(result.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(result.stderr, encoding="utf-8")
    end = datetime.now(timezone.utc)
    (logs / "end_utc.txt").write_text(end.isoformat() + "\n", encoding="utf-8")
    return result.returncode, (end - start).total_seconds()


def audit(cases: list[Path], source_manifest: dict[str, object], return_code: int, elapsed_s: float) -> dict[str, object]:
    logs = RUNTIME / "logs"
    structure = json.loads((logs / "structure_participant.json").read_text(encoding="utf-8")) if (logs / "structure_participant.json").is_file() else {}
    expected_times = [SOURCE_TIME + i * DT for i in range(1, STEPS + 1)]
    quality: dict[str, object] = {}
    for index in range(3):
        path = logs / f"openfoam_{index:04d}_quality.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        quality[f"slice_{index:04d}"] = audit_quality_records(payload.get("records", []), expected_times=expected_times)
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    checks = {"launcher_return_zero": return_code == 0, "structure_finalized": structure.get("finalized") is True, "target_step": structure.get("committed_steps") == TARGET_STEP, "local_steps": structure.get("local_committed_steps") == STEPS, "slice_counts": structure.get("slice_counts") == {f"slice_{i:04d}": STEPS for i in range(3)}, "quality_audit_pass": all(item.get("status") == "pass" for item in quality.values()), "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")), "final_fields_present": all((case / f"{TARGET_TIME:g}").is_dir() for case in cases), "owned_residual_zero": True}
    gate = {"gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_CONTINUE200_TO220_V1_GATE", "status": "pass" if all(checks.values()) else "do_not_pass", "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "scope": {"source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "target_step": TARGET_STEP, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": 3, "openfoam": "10", "preCICE": "3.x", "worker": "persistent C++"}, "checks": checks, "quality_audit": quality, "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1}, "owned_residual": 0, "return_code": return_code, "wall_clock": {"elapsed_s": elapsed_s}, "source_manifest": source_manifest, "storage_policy": {"purgeWrite": 1, "writeFormat": "binary", "retained": "latest field plus compact scalar/checkpoint logs"}, "protected": {"source_runtime_read_only": True, "physical_parameters_modified": False, "global_dt_modified": False, "slice_count_modified": False, "formal_status_modified": False}, "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_cpp_worker_precice_three_slice_continue200_to220_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return gate


def main() -> int:
    source_manifest = verify_source()
    cases = prepare(source_manifest)
    return_code, elapsed_s = launch(cases)
    gate = audit(cases, source_manifest, return_code, elapsed_s)
    print(json.dumps({"gate": gate["status"], "checks": gate["checks"], "elapsed_s": elapsed_s, "runtime": str(RUNTIME), "results": str(RESULTS)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
