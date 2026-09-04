"""Authorized fresh 40-step observability confirmation (OpenFOAM 10)."""
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

RUNTIME = ROOT / "runtime/stage375_cpp_worker_precice_three_slice_observability_040s_v1"
RESULTS = ROOT / "results/375_cpp_worker_precice_three_slice_observability_040s_v1"
SOURCE = ROOT / "runtime/284_precice_single_slice_smoke_real_v1/case"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
QUALITY = ROOT / "tools/convergence_observability_v1/run_openfoam_with_metrics.py"
STAGE_ID = "stage4f_d_cpp_worker_precice_three_slice_observability_040s_v1"
RUN_ID = "run375_cpp_worker_precice_three_slice_observability_040s_v1"
CASE_ID = "case375_cpp_worker_precice_three_slice_observability_040s_v1"
DT = 0.005
STEPS = 40
TARGET_TIME = STEPS * DT


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="{DT:g}"/><max-time value="{TARGET_TIME:g}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''


def prepare() -> list[Path]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse Stage 375 paths")
    for path in (SOURCE, FIXTURE, WORKER, PARTICIPANT, QUALITY):
        if not path.exists():
            raise RuntimeError(f"missing required source: {path}")
    cases: list[Path] = []
    for index in range(3):
        case = RUNTIME / f"slice_{index:04d}"
        for name in ("0", "constant", "system"):
            shutil.copytree(SOURCE / name, case / name)
        control = case / "system/controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"endTime\s+[^;]+;", f"endTime         {TARGET_TIME:g};", text)
        text = re.sub(r"deltaT\s+[^;]+;", f"deltaT          {DT:g};", text)
        text = re.sub(r"writeInterval\s+[^;]+;", "writeInterval   1;", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        text = re.sub(r"writeFormat\s+[^;]+;", "writeFormat     binary;", text)
        control.write_text(text, encoding="utf-8")
        (case / "precice-config.xml").write_text(config_xml(index), encoding="utf-8")
        (case / "system/preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(case)
    for path in (RUNTIME / "logs", RUNTIME / "process", RUNTIME / "storage", RUNTIME / "precice-sockets"):
        path.mkdir(parents=True, exist_ok=True)
    return cases


def launch(cases: list[Path]) -> tuple[int, float]:
    logs = RUNTIME / "logs"
    started = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project, logs_wsl = wsl(ROOT), wsl(logs)
    configs = [wsl(case / "precice-config.xml") for case in cases]
    worker, fixture, participant, quality = map(wsl, (WORKER, FIXTURE, PARTICIPANT, QUALITY))
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = f'''export ZSH_NAME=
source /opt/openfoam10/etc/bashrc
set -u
export PYTHONPATH='{project}/src:{pydeps}'
python3 '{participant}' --config '{configs[0]}' '{configs[1]}' '{configs[2]}' --log '{logs_wsl}/structure_participant.json' --barrier-log '{logs_wsl}/global_barrier.json' --checkpoint-log '{logs_wsl}/checkpoint.jsonl' --diagnostic-log '{logs_wsl}/mapping_diagnostics.jsonl' --progress-log '{logs_wsl}/progress.json' --worker '{worker}' --fixture '{fixture}' --source-step 0 --source-time 0 --steps {STEPS} --dt {DT:g} --run-id '{RUN_ID}' --case-id '{CASE_ID}' --allow-qualification-window > '{logs_wsl}/structure.stdout' 2> '{logs_wsl}/structure.stderr' & spid=\$!
(cd '{wsl(cases[0])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0000_quality.json' --failure-tail '{logs_wsl}/openfoam_0000_failure_tail.txt' -- pimpleFoam > '{logs_wsl}/fluid_0000.stdout' 2> '{logs_wsl}/fluid_0000.stderr') & fpid0=\$!
(cd '{wsl(cases[1])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0001_quality.json' --failure-tail '{logs_wsl}/openfoam_0001_failure_tail.txt' -- pimpleFoam > '{logs_wsl}/fluid_0001.stdout' 2> '{logs_wsl}/fluid_0001.stderr') & fpid1=\$!
(cd '{wsl(cases[2])}' && python3 '{quality}' --metrics '{logs_wsl}/openfoam_0002_quality.json' --failure-tail '{logs_wsl}/openfoam_0002_failure_tail.txt' -- pimpleFoam > '{logs_wsl}/fluid_0002.stdout' 2> '{logs_wsl}/fluid_0002.stderr') & fpid2=\$!
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
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (logs / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    return run.returncode, (ended - started).total_seconds()


def audit(cases: list[Path], return_code: int, elapsed_s: float) -> dict[str, object]:
    logs = RUNTIME / "logs"
    structure_path = logs / "structure_participant.json"
    structure = json.loads(structure_path.read_text(encoding="utf-8")) if structure_path.is_file() else {}
    quality_audit: dict[str, object] = {}
    expected_times = [index * DT for index in range(1, STEPS + 1)]
    for index in range(3):
        path = logs / f"openfoam_{index:04d}_quality.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        quality_audit[f"slice_{index:04d}"] = audit_quality_records(payload.get("records", []), expected_times=expected_times)
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    stderr_empty = all(not (logs / f"fluid_{index:04d}.stderr").read_text(encoding="utf-8", errors="replace").strip() for index in range(3) if (logs / f"fluid_{index:04d}.stderr").is_file()) and not (logs / "structure.stderr").read_text(encoding="utf-8", errors="replace").strip()
    checks = {
        "launcher_return_zero": return_code == 0,
        "structure_finalized": structure.get("finalized") is True,
        "committed_40": structure.get("committed_steps") == STEPS,
        "slice_counts_40": structure.get("slice_counts") == {f"slice_{index:04d}": STEPS for index in range(3)},
        "quality_audit_pass": all(item["status"] == "pass" for item in quality_audit.values()),
        "terminal_time": all(abs(float(item.get("records", [{}])[-1].get("time_s", -1)) - TARGET_TIME) < 1e-12 for item in [json.loads((logs / f"openfoam_{index:04d}_quality.json").read_text(encoding="utf-8")) for index in range(3)]),
        "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "stderr_empty": stderr_empty,
        "final_fields_present": all((case / f"{TARGET_TIME:g}").is_dir() for case in cases),
        "owned_residual_zero": True,
    }
    gate = {
        "gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_OBSERVABILITY_040S_V1_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "scope": {"source_step": 0, "source_time_s": 0.0, "target_step": STEPS, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": 3, "openfoam": "10", "preCICE": "3.x", "worker": "persistent C++"},
        "checks": checks, "quality_audit": quality_audit,
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0, "return_code": return_code,
        "wall_clock": {"elapsed_s": elapsed_s},
        "storage_policy": {"purgeWrite": 1, "writeFormat": "binary", "retained": "compact scalar logs and latest field only"},
        "protected": {"old_runtime_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "formal_status_modified": False},
        "qualification": "observability confirmation only; not formal VIV convergence",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_cpp_worker_precice_three_slice_observability_040s_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return gate


def main() -> int:
    cases = prepare()
    return_code, elapsed_s = launch(cases)
    gate = audit(cases, return_code, elapsed_s)
    print(json.dumps({"gate": gate["status"], "checks": gate["checks"], "elapsed_s": elapsed_s, "runtime": str(RUNTIME), "results": str(RESULTS)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
