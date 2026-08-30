"""Run one fresh three-slice fine-dt sensitivity window.

This launcher is intentionally limited to 1.0 s from a fresh zero state.  It
uses the already-qualified inverseDistance mesh profile and retains only the
final OpenFOAM field (purgeWrite=1), a compact tail, checkpoints, and audit
logs.  No MATLAB process is started.  The 0.00125 s value is the fine
sensitivity level from the project freeze, not the production coarse dt.
"""
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
sys.path.insert(0, str(ROOT / "tools/stage308_moving_mesh_smoke_v1"))
from run_stage308_smoke import corrected_dynamic_mesh  # type: ignore
SOURCE = ROOT / "runtime/stage304_interface_mapping_repair_v1_fresh_zero_to80s/slice_0000"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
RUNTIME = ROOT / "runtime/stage335_formal_dt_qualification_v1_inverse_distance_1s"
RESULTS = ROOT / "results/335_formal_dt_qualification_v1_inverse_distance_1s"
DT = 0.00125
STEPS = 800
TARGET = 1.0


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_xml(index: int, socket: Path) -> str:
    name = f"{index:04d}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{wsl(socket)}"/>
<participant name="Structure_{name}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="{DT:.8f}"/><max-time value="{TARGET:.8f}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def precice_dict(index: int) -> str:
    return f'''FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object preciceDict; }}
preciceConfig "precice-config.xml"; participant Fluid_{index:04d}; modules (FSI);
FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement unused; nameCellDisplacement cellDisplacement; nameForce Force; }}
interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cyl); locations faceCenters; readData (Displacement); writeData (Force); }} }}'''


def prepare() -> list[Path]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse Stage335 runtime/results")
    for path in (SOURCE, FIXTURE, WORKER, PARTICIPANT):
        if not path.exists():
            raise RuntimeError(f"required source missing: {path}")
    cases: list[Path] = []
    for index in range(3):
        case = RUNTIME / f"slice_{index:04d}"
        for name in ("0", "constant", "system"):
            shutil.copytree(SOURCE / name, case / name)
        control_path = case / "system/controlDict"
        control = control_path.read_text(encoding="utf-8")
        control = re.sub(r"startFrom\s+[^;]+;", "startFrom       startTime;", control)
        control = re.sub(r"startTime\s+[^;]+;", "startTime       0;", control)
        control = re.sub(r"endTime\s+[^;]+;", f"endTime         {TARGET:g};", control)
        control = re.sub(r"deltaT\s+[^;]+;", f"deltaT          {DT:g};", control)
        control = re.sub(r"writeInterval\s+[^;]+;", "writeInterval   1;", control)
        control = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", control)
        control = re.sub(r"writeFormat\s+[^;]+;", "writeFormat     binary;", control)
        control_path.write_text(control, encoding="utf-8")
        fv_path = case / "system/fvSolution"
        fv = fv_path.read_text(encoding="utf-8").replace("chacheAgglomeration", "cacheAgglomeration")
        fv = re.sub(r"(moveMeshOuterCorrectors\s+)yes\s*;", r"\1no;", fv)
        fv_path.write_text(fv, encoding="utf-8")
        (case / "constant/dynamicMeshDict").write_text(corrected_dynamic_mesh("inverseDistance"), encoding="utf-8")
        (case / "precice-config.xml").write_text(config_xml(index, RUNTIME / "precice-sockets"), encoding="utf-8")
        (case / "system/preciceDict").write_text(precice_dict(index), encoding="utf-8")
        cases.append(case)
    for path in (RUNTIME / "logs", RUNTIME / "process", RUNTIME / "storage"):
        path.mkdir(parents=True, exist_ok=True)
    return cases


def main() -> int:
    cases = prepare()
    logs = RUNTIME / "logs"
    started = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project, log_dir, worker, fixture, participant = map(wsl, (ROOT, logs, WORKER, FIXTURE, PARTICIPANT))
    configs = " ".join(wsl(case / "precice-config.xml") for case in cases)
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        f"export PYTHONPATH='{project}/src:{pydeps}';",
        f"python3 '{participant}' --config {configs} --log '{log_dir}/structure_participant.json' --barrier-log '{log_dir}/global_barrier.json' --checkpoint-log '{log_dir}/checkpoint.jsonl' --convergence-log '{log_dir}/convergence_summary.json' --diagnostic-log '{log_dir}/mapping_diagnostics.jsonl' --progress-log '{log_dir}/progress.json' --worker '{worker}' --fixture '{fixture}' --source-step 0 --source-time 0 --steps {STEPS} --dt {DT} --run-id 's335_inverse_distance_formal_dt_1s_v1' --case-id 'c335_inverse_distance_formal_dt_1s_v1' --allow-qualification-window > /dev/null 2> '{log_dir}/structure.stderr' & spid=\$!;",
        f"(cd '{wsl(cases[0])}' && pimpleFoam > /dev/null 2> '{log_dir}/fluid_0000.stderr') & f0=\$!;",
        f"(cd '{wsl(cases[1])}' && pimpleFoam > /dev/null 2> '{log_dir}/fluid_0001.stderr') & f1=\$!;",
        f"(cd '{wsl(cases[2])}' && pimpleFoam > /dev/null 2> '{log_dir}/fluid_0002.stderr') & f2=\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\$spid\" \"\$f0\" \"\$f1\" \"\$f2\" > '{log_dir}/pids.txt';",
        "set +e; wait \"\$spid\"; sr=\$?; wait \"\$f0\"; r0=\$?; wait \"\$f1\"; r1=\$?; wait \"\$f2\"; r2=\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\$sr\" \"\$r0\" \"\$r1\" \"\$r2\" > '{log_dir}/returns.txt';",
        "if [ \"\$sr\" -ne 0 ] || [ \"\$r0\" -ne 0 ] || [ \"\$r1\" -ne 0 ] || [ \"\$r2\" -ne 0 ]; then exit 1; fi",
    ])
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (logs / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    structure_path = logs / "structure_participant.json"
    structure = json.loads(structure_path.read_text(encoding="utf-8")) if structure_path.is_file() else {}
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    errors = [(logs / f"fluid_{i:04d}.stderr").read_text(encoding="utf-8", errors="replace") if (logs / f"fluid_{i:04d}.stderr").is_file() else "" for i in range(3)]
    counts = structure.get("slice_counts", {})
    checks = {
        "launcher_return_zero": run.returncode == 0,
        "structure_finalized": structure.get("finalized") is True,
        "committed_800": structure.get("committed_steps") == STEPS and structure.get("local_committed_steps") == STEPS,
        "slice_counts_800": all(counts.get(f"slice_{i:04d}") == STEPS for i in range(3)),
        "checkpoint_count_8": structure.get("checkpoint_count") == 8,
        "tail_records_20": len(structure.get("tail_records", [])) == 20,
        "target_time_1s": abs(float(structure.get("target_time_s", -1)) - TARGET) < 1e-12,
        "worker_closed_zero": structure.get("worker", {}).get("closed") is True and structure.get("worker", {}).get("return_code") == 0,
        "fluid_stderr_empty": all(not item.strip() for item in errors),
        "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "final_fields_present": all((case / "1" / "cellDisplacement").is_file() for case in cases),
        "purge_write_enabled": all("purgeWrite      1;" in (case / "system/controlDict").read_text(encoding="utf-8") for case in cases),
        "formal_convergence_not_claimed": structure.get("convergence_observables", {}).get("formal_convergence") == "not_completed",
    }
    gate_status = "pass" if all(checks.values()) else "do_not_pass"
    gate = {
        "gate_id": "STAGE4F_D_FORMAL_DT_INVERSE_DISTANCE_1S_QUALIFICATION_V1_GATE",
        "status": gate_status,
        "stage_id": "stage335_formal_dt_qualification_v1_inverse_distance_1s",
        "run_id": "s335_inverse_distance_formal_dt_1s_v1",
        "case_id": "c335_inverse_distance_formal_dt_1s_v1",
        "scope": {"source_step": 0, "source_time_s": 0.0, "target_step": STEPS, "target_time_s": TARGET, "dt_s": DT, "slice_count": 3, "mesh_method": "inverseDistance 1(cyl)"},
        "checks": checks,
        "wall_clock": {"start_utc": started.isoformat(), "end_utc": ended.isoformat(), "elapsed_s": (ended - started).total_seconds()},
        "source_hashes": {"worker": sha(WORKER), "fixture": sha(FIXTURE), "participant": sha(PARTICIPANT), "source_control": sha(SOURCE / "system/controlDict")},
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "protected": {"ancf_eb_core_modified": False, "physical_parameters_modified": False, "slice_count_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False},
        "qualification": "fine-dt sensitivity 1.0 s three-slice qualification; production coarse dt is 0.0025 s; not formal VIV convergence",
        "next_authorization": "new explicit authorization required before any longer run",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_formal_dt_inverse_distance_1s_qualification_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "structure_participant.json").write_text(json.dumps(structure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": gate_status, "elapsed_s": gate["wall_clock"]["elapsed_s"], "checks": checks}, ensure_ascii=False))
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
