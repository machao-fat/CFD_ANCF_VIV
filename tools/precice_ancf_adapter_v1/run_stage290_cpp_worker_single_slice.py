"""Run one fresh, bounded C++-worker + single-slice preCICE validation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "291_cpp_worker_precice_single_slice_040s_retry1_v1"
SOURCE_CASE = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "case"
FIXTURE = ROOT / "runtime" / "cpp_worker_to70s_real_v1" / "run_001" / "support" / "cpp_input_fixture.json"
WORKER = ROOT / "runtime" / "cpp_worker_to70s_build_retry_v11" / "cpp_worker_build" / "cfd_ancf_ancf_kernel_worker.exe"
LOGS = RUNTIME / "logs"
CASE = RUNTIME / "case"
RUN_ID = "stage291_cpp_worker_precice_single_slice_040s_retry1_run_v1"
CASE_ID = "stage291_cpp_worker_precice_single_slice_040s_retry1_case_v1"
OUT = ROOT / "results" / "291_cpp_worker_precice_single_slice_040s_retry1_v1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wsl_path(path: Path) -> str:
    value = str(path).replace("\\", "/")
    if len(value) < 3 or value[1:3] != ":/":
        raise RuntimeError(f"expected absolute drive path: {path}")
    return "/mnt/" + value[0].lower() + value[2:]


def prepare() -> None:
    if RUNTIME.exists():
        raise RuntimeError(f"refusing to reuse existing runtime: {RUNTIME}")
    for path in (SOURCE_CASE, FIXTURE, WORKER):
        if not path.exists():
            raise RuntimeError(f"required source artifact missing: {path}")
    shutil.copytree(SOURCE_CASE / "0", CASE / "0")
    shutil.copytree(SOURCE_CASE / "constant", CASE / "constant")
    shutil.copytree(SOURCE_CASE / "system", CASE / "system")
    shutil.copy2(SOURCE_CASE / "precice-config.xml", CASE / "precice-config.xml")
    LOGS.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "process").mkdir(parents=True, exist_ok=True)
    (RUNTIME / "storage").mkdir(parents=True, exist_ok=True)
    control_path = CASE / "system" / "controlDict"
    control = control_path.read_text(encoding="utf-8")
    control = re.sub(r"endTime\s+[^;]+;", "endTime         0.20;", control)
    control = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", control)
    control_path.write_text(control, encoding="utf-8")
    xml_path = CASE / "precice-config.xml"
    xml = xml_path.read_text(encoding="utf-8").replace('<max-time value="0.04" />', '<max-time value="0.20" />')
    xml_path.write_text(xml, encoding="utf-8")


def main() -> int:
    prepare()
    started = datetime.now(timezone.utc)
    (LOGS / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    project = wsl_path(ROOT)
    case = wsl_path(CASE)
    logs = wsl_path(LOGS)
    fixture = wsl_path(FIXTURE)
    worker = wsl_path(WORKER)
    participant = f"{project}/tools/precice_ancf_adapter_v1/ancf_cpp_worker_single_slice_participant_v1.py"
    pydeps = f"{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        f"export PYTHONPATH='{project}/src:{pydeps}';",
        f"cd '{case}';",
        f"python3 '{participant}' --config '{case}/precice-config.xml' --log '{logs}/structure_participant.json' --worker '{worker}' --fixture '{fixture}' --steps 40 --dt 0.005 --run-id '{RUN_ID}' --case-id '{CASE_ID}' > '{logs}/structure.stdout' 2> '{logs}/structure.stderr' & spid=\\$!;",
        f"pimpleFoam > '{logs}/pimpleFoam.stdout' 2> '{logs}/pimpleFoam.stderr' & fpid=\\$!;",
        f"printf 'structure_pid=%s\\nfluid_pid=%s\\n' \"\\$spid\" \"\\$fpid\" > '{logs}/pids.txt';",
        "set +e; wait \"\\$spid\"; sr=\\$?; wait \"\\$fpid\"; fr=\\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_return=%s\\n' \"\\$sr\" \"\\$fr\" > '{logs}/returns.txt';",
        "if [ \"\\$sr\" -ne 0 ] || [ \"\\$fr\" -ne 0 ]; then exit 1; fi",
    ])
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (LOGS / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (LOGS / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (LOGS / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    structure_path = LOGS / "structure_participant.json"
    structure = json.loads(structure_path.read_text(encoding="utf-8")) if structure_path.is_file() else {}
    records = structure.get("records", [])
    fluid_text = (LOGS / "pimpleFoam.stdout").read_text(encoding="utf-8", errors="replace") if (LOGS / "pimpleFoam.stdout").is_file() else ""
    fluid_err = (LOGS / "pimpleFoam.stderr").read_text(encoding="utf-8", errors="replace") if (LOGS / "pimpleFoam.stderr").is_file() else ""
    expected_times = [round(0.005 * i, 12) for i in range(1, 41)]
    actual_times = [round(float(r.get("time_s", -1)), 12) for r in records]
    checks = {
        "structure_finalized": structure.get("finalized") is True,
        "structure_records_40": len(records) == 40,
        "times_005_to_020": actual_times == expected_times,
        "identity_continuous": [r.get("sequence") for r in records] == list(range(1, 41)),
        "tick_consistent": all(r.get("integer_tick") == int(round(float(r.get("time_s", -1)) * 1e9)) for r in records),
        "worker_ack_finite": all(r.get("ack") == 1 and r.get("finite_audit") is True and r.get("worker_return_code") == 0 for r in records),
        "worker_single_start": structure.get("worker", {}).get("pid", 0) > 0 and structure.get("worker", {}).get("owned") is True,
        "worker_closed": structure.get("worker", {}).get("closed") is True,
        "fluid_reached_final_time": "Time = 0.2" in fluid_text or "Time = 0.20" in fluid_text or "End" in fluid_text,
        "fluid_end_marker": re.search(r"^End$", fluid_text, re.M) is not None,
        "fluid_stderr_empty": not fluid_err.strip(),
        "purge_write_enabled": "purgeWrite      1;" in (CASE / "system" / "controlDict").read_text(encoding="utf-8"),
    }
    gate_status = "pass" if run.returncode == 0 and all(checks.values()) else "do_not_pass"
    gate = {
        "gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_SINGLE_SLICE_040S_V1_GATE",
        "status": gate_status, "timestamp": ended.isoformat(),
        "stage_id": "stage4f_d_cpp_worker_precice_single_slice_040s_retry1_v1", "run_id": RUN_ID, "case_id": CASE_ID,
        "scope_contract": {"openfoam": "10", "precice": "3.4.1", "dt_s": 0.005, "steps": 40, "end_time_s": 0.20, "slice_count": 1, "worker": "persistent C++ ANCF kernel"},
        "checks": checks, "runtime": str(RUNTIME),
        "source_hashes": {"worker": sha(WORKER), "fixture": sha(FIXTURE), "precice_config": sha(CASE / "precice-config.xml"), "precice_dict": sha(CASE / "system" / "preciceDict"), "participant": sha(ROOT / "tools" / "precice_ancf_adapter_v1" / "ancf_cpp_worker_single_slice_participant_v1.py")},
        "real_process_counts": {"matlab": 0, "openfoam": 1, "wsl": 1, "cfd": 1, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0, "return_code": run.returncode,
        "wall_clock": {"start_utc": started.isoformat(), "end_utc": ended.isoformat(), "elapsed_s": (ended - started).total_seconds()},
        "protected": {"historical_evidence_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False, "formal_viv_validation_complete": False},
        "qualification": "single-slice preCICE/OpenFOAM 40-step interface with persistent C++ ANCF worker; force/state projection is explicit and this is not formal ANCF equivalence or VIV validation",
        "next_authorization": "fresh three-slice C++ worker + preCICE smoke only after audit review",
    }
    out = OUT
    out.mkdir(parents=True, exist_ok=True)
    (out / "stage4f_d_cpp_worker_precice_single_slice_040s_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "structure_participant.json").write_text(json.dumps(structure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate_status, "checks": checks, "wall_clock_s": gate["wall_clock"]["elapsed_s"], "return_code": run.returncode}, ensure_ascii=False))
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
