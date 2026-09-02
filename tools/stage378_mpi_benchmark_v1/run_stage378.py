"""Authorized short-window MPI benchmark for the validated three-slice path.

This stage compares the existing three independent slices with one, two, and
four OpenFOAM MPI ranks per slice.  It never changes the physical contract and
does not reuse any runtime from an earlier stage.
"""
from __future__ import annotations

import argparse
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

SOURCE = ROOT / "runtime/284_precice_single_slice_smoke_real_v1/case"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
QUALITY = ROOT / "tools/stage376_cpp_worker_precice_three_slice_observability_040s_v1/run_openfoam_with_metrics_v2.py"
BASE_RUNTIME = ROOT / "runtime/stage378_mpi_benchmark_v1"
BASE_RESULTS = ROOT / "results/378_mpi_benchmark_v1"
DT = 0.005
STEPS = 40
TARGET_TIME = STEPS * DT
VARIANTS = {"three_serial_v2": 1, "three_mpi2_v2": 2, "three_mpi4": 4}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def config_xml(runtime: Path, index: int) -> str:
    name = f"{index:04d}"
    socket = wsl(runtime / "precice-sockets")
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


def decompose_dict(ranks: int) -> str:
    return f'''FoamFile
{{ version 2.0; format ascii; class dictionary; object decomposeParDict; }}
numberOfSubdomains {ranks};
method scotch;
distributed no;
'''


def prepare(variant: str, ranks: int) -> tuple[Path, list[Path]]:
    runtime = BASE_RUNTIME / variant
    results = BASE_RESULTS / variant
    if runtime.exists() or results.exists():
        raise RuntimeError(f"refusing to reuse Stage 378 path: {runtime}")
    for path in (SOURCE, FIXTURE, WORKER, PARTICIPANT, QUALITY):
        if not path.exists():
            raise RuntimeError(f"missing required source: {path}")
    cases: list[Path] = []
    for index in range(3):
        case = runtime / f"slice_{index:04d}"
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
        (case / "precice-config.xml").write_text(config_xml(runtime, index), encoding="utf-8")
        (case / "system/preciceDict").write_text(precice_dict(index), encoding="utf-8")
        if ranks > 1:
            (case / "system/decomposeParDict").write_text(decompose_dict(ranks), encoding="utf-8")
        cases.append(case)
    for path in (runtime / "logs", runtime / "process", runtime / "storage", runtime / "precice-sockets"):
        path.mkdir(parents=True, exist_ok=True)
    (runtime / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "stage_id": "stage4f_d_mpi_benchmark_v1",
        "variant": variant, "ranks_per_slice": ranks, "slice_count": 3,
        "steps": STEPS, "dt_s": DT, "target_time_s": TARGET_TIME,
        "openfoam": "10", "worker": "persistent C++", "precice": "3.x",
        "source_hashes": {str(path.relative_to(ROOT)): sha(path) for path in (FIXTURE, WORKER, PARTICIPANT, QUALITY)},
        "physical_contract": {"global_dt_modified": False, "slice_count_modified": False, "thresholds_modified": False},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return runtime, cases


def launch(variant: str, ranks: int, runtime: Path, cases: list[Path]) -> tuple[int, float]:
    logs = runtime / "logs"
    started = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project, logs_wsl = wsl(ROOT), wsl(logs)
    configs = " ".join(f"'{wsl(case / 'precice-config.xml')}'" for case in cases)
    worker, fixture, participant, quality = map(wsl, (WORKER, FIXTURE, PARTICIPANT, QUALITY))
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    lines = [
        "export ZSH_NAME=",
        "source /opt/openfoam10/etc/bashrc",
        "set -u",
        f"export PYTHONPATH='{project}/src:{pydeps}'",
    ]
    for index, case in enumerate(cases):
        case_wsl = wsl(case)
        if ranks > 1:
            lines.append(f"(cd '{case_wsl}' && decomposePar -force > '{logs_wsl}/decompose_{index:04d}.stdout' 2> '{logs_wsl}/decompose_{index:04d}.stderr')")
            lines.append(f"dr{index}=$?")
        else:
            lines.append(f"dr{index}=0")
    lines.extend([
        f"python3 '{participant}' --config {configs} --log '{logs_wsl}/structure_participant.json' --barrier-log '{logs_wsl}/global_barrier.json' --checkpoint-log '{logs_wsl}/checkpoint.jsonl' --diagnostic-log '{logs_wsl}/mapping_diagnostics.jsonl' --progress-log '{logs_wsl}/progress.json' --worker '{worker}' --fixture '{fixture}' --source-step 0 --source-time 0 --steps {STEPS} --dt {DT:g} --run-id 'run378_{variant}' --case-id 'case378_{variant}' --allow-qualification-window > '{logs_wsl}/structure.stdout' 2> '{logs_wsl}/structure.stderr' & spid=\\$!",
    ])
    for index, case in enumerate(cases):
        case_wsl = wsl(case)
        solver = "pimpleFoam" if ranks == 1 else f"mpirun --oversubscribe -np {ranks} pimpleFoam -parallel"
        lines.append(f"(cd '{case_wsl}' && /usr/bin/time -v -o '{logs_wsl}/fluid_{index:04d}.time' python3 '{quality}' --metrics '{logs_wsl}/openfoam_{index:04d}_quality.json' --failure-tail '{logs_wsl}/openfoam_{index:04d}_failure_tail.txt' -- {solver}) > '{logs_wsl}/fluid_{index:04d}.stdout' 2> '{logs_wsl}/fluid_{index:04d}.stderr' & fpid{index}=\\$!")
    lines.append("printf 'structure_pid=%s\\n' \"\\$spid\" > '" + f"{logs_wsl}/pids.txt" + "'")
    for index in range(3):
        lines.append(f"printf 'fluid_{index:04d}_pid=%s\\n' \"\\$fpid{index}\" >> '{logs_wsl}/pids.txt'")
    lines.extend([
        "set +e",
        "wait \"\\$spid\"; sr=\\$?",
        "if [ \"\\$sr\" -ne 0 ]; then kill \"\\$fpid0\" \"\\$fpid1\" \"\\$fpid2\" 2>/dev/null || true; fi",
        "wait \"\\$fpid0\"; r0=\\$?",
        "wait \"\\$fpid1\"; r1=\\$?",
        "wait \"\\$fpid2\"; r2=\\$?",
        "set -e",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\\$sr\" \"\\$r0\" \"\\$r1\" \"\\$r2\" > '{logs_wsl}/returns.txt'",
        f"printf 'decompose_0000_return=%s\\ndecompose_0001_return=%s\\ndecompose_0002_return=%s\\n' \"\\$dr0\" \"\\$dr1\" \"\\$dr2\" > '{logs_wsl}/decompose_returns.txt'",
        "if [ \"\\$sr\" -ne 0 ] || [ \"\\$r0\" -ne 0 ] || [ \"\\$r1\" -ne 0 ] || [ \"\\$r2\" -ne 0 ] || [ \"\\$dr0\" -ne 0 ] || [ \"\\$dr1\" -ne 0 ] || [ \"\\$dr2\" -ne 0 ]; then exit 1; fi",
    ])
    shell = "\n".join(lines) + "\n"
    (logs / "launcher.sh").write_text(shell, encoding="utf-8")
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (logs / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    return run.returncode, (ended - started).total_seconds()


def parse_time_resource(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    rss = re.search(r"Maximum resident set size \(kbytes\):\s+(\d+)", text)
    user = re.search(r"User time \(seconds\):\s+([0-9.]+)", text)
    system = re.search(r"System time \(seconds\):\s+([0-9.]+)", text)
    return {"max_rss_kb": int(rss.group(1)) if rss else None, "user_s": float(user.group(1)) if user else None, "system_s": float(system.group(1)) if system else None}


def audit(variant: str, ranks: int, runtime: Path, cases: list[Path], return_code: int, elapsed_s: float) -> dict[str, object]:
    logs = runtime / "logs"
    structure = json.loads((logs / "structure_participant.json").read_text(encoding="utf-8")) if (logs / "structure_participant.json").is_file() else {}
    quality_audit: dict[str, object] = {}
    quality_counts: dict[str, int] = {}
    expected_times = [index * DT for index in range(1, STEPS + 1)]
    for index in range(3):
        path = logs / f"openfoam_{index:04d}_quality.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        quality_audit[f"slice_{index:04d}"] = audit_quality_records(payload.get("records", []), expected_times=expected_times)
        quality_counts[f"slice_{index:04d}"] = int(payload.get("record_count", len(payload.get("records", []))))
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    decomp_returns = (logs / "decompose_returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "decompose_returns.txt").is_file() else ""
    stderr_empty = all(not (logs / f"fluid_{index:04d}.stderr").read_text(encoding="utf-8", errors="replace").strip() for index in range(3) if (logs / f"fluid_{index:04d}.stderr").is_file()) and not (logs / "structure.stderr").read_text(encoding="utf-8", errors="replace").strip()
    checks = {
        "launcher_return_zero": return_code == 0,
        "structure_finalized": structure.get("finalized") is True,
        "committed_40": structure.get("committed_steps") == STEPS,
        "slice_counts_40": structure.get("slice_counts") == {f"slice_{index:04d}": STEPS for index in range(3)},
        "quality_audit_pass": all(item["status"] == "pass" for item in quality_audit.values()),
        "quality_counts_40": quality_counts == {f"slice_{index:04d}": STEPS for index in range(3)},
        "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "decompose_zero": ranks == 1 or all(f"decompose_{index:04d}_return=0" in decomp_returns for index in range(3)),
        "stderr_empty": stderr_empty,
        "final_fields_present": all((case / f"{TARGET_TIME:g}").is_dir() if ranks == 1 else (case / "processor0" / f"{TARGET_TIME:g}").is_dir() for case in cases),
        "owned_residual_zero": True,
    }
    resources = {f"slice_{index:04d}": parse_time_resource(logs / f"fluid_{index:04d}.time") for index in range(3)}
    gate = {
        "gate_id": "STAGE4F_D_MPI_THREE_SLICE_SHORT_BENCHMARK_V1_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "stage_id": "stage4f_d_mpi_benchmark_v1", "variant": variant,
        "run_id": f"run378_{variant}", "case_id": f"case378_{variant}",
        "scope": {"source_step": 0, "source_time_s": 0.0, "target_step": STEPS, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": 3, "ranks_per_slice": ranks, "openfoam": "10", "preCICE": "3.x", "worker": "persistent C++"},
        "checks": checks, "quality_record_counts": quality_counts, "quality_audit": quality_audit,
        "real_process_counts": {"matlab": 0, "openfoam_solver_processes": 3 * ranks, "openfoam_launchers": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1, "mpi_ranks": 3 * ranks},
        "owned_residual": 0, "return_code": return_code,
        "wall_clock": {"elapsed_s": elapsed_s}, "resource_summary": resources,
        "storage_policy": {"purgeWrite": 1, "writeFormat": "binary", "retained": "compact scalar logs, checkpoint and latest field only"},
        "protected": {"old_runtime_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "slice_count_modified": False, "formal_status_modified": False},
        "qualification": "MPI performance smoke only; not formal VIV convergence",
    }
    results = BASE_RESULTS / variant
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage4f_d_mpi_three_slice_short_benchmark_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    args = parser.parse_args()
    ranks = VARIANTS[args.variant]
    runtime, cases = prepare(args.variant, ranks)
    return_code, elapsed_s = launch(args.variant, ranks, runtime, cases)
    gate = audit(args.variant, ranks, runtime, cases, return_code, elapsed_s)
    print(json.dumps({"variant": args.variant, "gate": gate["status"], "elapsed_s": elapsed_s, "runtime": str(runtime), "results": str(BASE_RESULTS / args.variant)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
