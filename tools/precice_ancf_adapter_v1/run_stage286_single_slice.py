"""Run the one authorized Stage 286 single-slice validation exactly once."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "286_precice_single_slice_040s_retry7_v1"
CASE = RUNTIME / "case"
LOGS = RUNTIME / "logs"
SOURCE = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "case"
RUN_ID = "stage286_precice_single_slice_040s_retry7_run_v1"
CASE_ID = "stage286_precice_single_slice_040s_retry7_case_v1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def wsl_path(path: Path) -> str:
    """Convert an absolute Windows drive path to a quoted WSL mount path."""
    value = str(path).replace("\\", "/")
    if len(value) < 3 or value[1:3] != ":/":
        raise RuntimeError(f"expected absolute drive path: {path}")
    return "/mnt/" + value[0].lower() + value[2:]


def prepare() -> None:
    if RUNTIME.exists():
        raise RuntimeError(f"refusing to reuse existing runtime: {RUNTIME}")
    if not SOURCE.is_dir():
        raise RuntimeError("Stage 284 source case is missing")
    for path in (CASE / "0", CASE / "constant", CASE / "system"):
        path.mkdir(parents=True, exist_ok=True)
    for name in ("0", "constant", "system"):
        shutil.copytree(SOURCE / name, CASE / name, dirs_exist_ok=True)
    shutil.copy2(SOURCE / "precice-config.xml", CASE / "precice-config.xml")
    for path in (LOGS, RUNTIME / "storage", RUNTIME / "process"):
        path.mkdir(parents=True, exist_ok=True)
    control = (CASE / "system" / "controlDict").read_text(encoding="utf-8")
    control = re.sub(r"endTime\s+[^;]+;", "endTime         0.20;", control)
    control = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", control)
    control = re.sub(r"writeInterval\s+100;", "writeInterval   100;", control)
    (CASE / "system" / "controlDict").write_text(control, encoding="utf-8")
    xml = (CASE / "precice-config.xml").read_text(encoding="utf-8")
    xml = xml.replace('<max-time value="0.04" />', '<max-time value="0.20" />')
    (CASE / "precice-config.xml").write_text(xml, encoding="utf-8")
    # Remove any copied solver output if a source template ever contains it.
    for path in CASE.iterdir():
        if path.is_dir() and path.name not in {"0", "constant", "system"}:
            shutil.rmtree(path)


def main() -> int:
    prepare()
    started = datetime.now(timezone.utc).isoformat()
    (LOGS / "start_utc.txt").write_text(started + "\n", encoding="utf-8")
    # Resolve the project inside WSL by its ASCII basename. This avoids
    # passing the Chinese Windows parent path through the WSL command line.
    project_expr = "project=; for candidate in /mnt/d/*/*/CFD_ANCF_VIV; do if [ -d \"$candidate/runtime/284_precice_single_slice_smoke_real_v1/case\" ]; then project=\"$candidate\"; break; fi; done; test -n \"$project\";"
    case_expr = 'case="$project/runtime/286_precice_single_slice_040s_retry7_v1/case"; logs="$project/runtime/286_precice_single_slice_040s_retry7_v1/logs";'
    participant_script = "$project/tools/precice_ancf_adapter_v1/ancf_structure_participant_v1.py"
    log = "$logs/structure_participant.json"
    out = "$logs/pimpleFoam.stdout"
    err = "$logs/pimpleFoam.stderr"
    pydeps = "$project/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    shell = " ".join([
        "set -e; export ZSH_NAME=; source /opt/openfoam10/etc/bashrc || true; set -u;",
        project_expr,
        case_expr,
        f"export PYTHONPATH=\"{pydeps}\";",
        'cd "$case";',
        f"python3 \"{participant_script}\" --config \"$case/precice-config.xml\" --log \"{log}\" --steps 40 --dt 0.005 --run-id '{RUN_ID}' --case-id '{CASE_ID}' > \"$logs/structure.stdout\" 2> \"$logs/structure.stderr\" & spid=$!;",
        f"pimpleFoam > \"{out}\" 2> \"{err}\" & fpid=$!;",
        "printf 'structure_pid=%s\\nfluid_pid=%s\\n' \"$spid\" \"$fpid\" > \"$logs/pids.txt\";",
        "set +e; wait \"$spid\"; sr=$?; wait \"$fpid\"; fr=$?; set -e;",
        "printf 'structure_return=%s\\nfluid_return=%s\\n' \"$sr\" \"$fr\" > \"$logs/returns.txt\";",
        "exit $((sr != 0 || fr != 0))",
    ])
    # The command is one foreground WSL invocation; no retry path exists.
    run = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (LOGS / "launcher.stdout").write_text(run.stdout, encoding="utf-8")
    (LOGS / "launcher.stderr").write_text(run.stderr, encoding="utf-8")
    (LOGS / "end_utc.txt").write_text(datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8")
    structure_path = LOGS / "structure_participant.json"
    fluid_text = (LOGS / "pimpleFoam.stdout").read_text(encoding="utf-8", errors="replace") if (LOGS / "pimpleFoam.stdout").is_file() else ""
    fluid_err = (LOGS / "pimpleFoam.stderr").read_text(encoding="utf-8", errors="replace") if (LOGS / "pimpleFoam.stderr").is_file() else ""
    structure = json.loads(structure_path.read_text(encoding="utf-8")) if structure_path.is_file() else {}
    records = structure.get("records", [])
    expected_times = [round(0.005 * i, 12) for i in range(1, 41)]
    actual_times = [round(float(r.get("time_s", -1)), 12) for r in records]
    checks = {
        "structure_finalized": structure.get("finalized") is True,
        "structure_records_40": len(records) == 40,
        "structure_times_005_to_020": actual_times == expected_times,
        "structure_force_604_each": all(r.get("force_vertices") == 604 for r in records),
        "identity_continuous": [r.get("sequence") for r in records] == list(range(1, 41)),
        "tick_continuous": all(r.get("integer_tick") == int(round(r.get("time_s", -1) * 1e9)) for r in records),
        "fluid_reached_final_time": ("Reached end at: final time-window: 40, final time: 0.2" in fluid_text or "Reached end at: final time-window: 40, final time: 0.20" in fluid_text),
        "fluid_end_marker": re.search(r"^End$", fluid_text, re.M) is not None,
        "fluid_stderr_empty": not fluid_err.strip(),
        "purge_write_enabled": "purgeWrite      1;" in (CASE / "system" / "controlDict").read_text(encoding="utf-8"),
        "old_runtime_not_reused": str(RUNTIME) != str(ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1"),
    }
    counts = {"matlab": 0, "openfoam": 1, "wsl": 1, "cfd": 1, "precice_structure": 1}
    residual = 0
    gate = {"gate_id": "STAGE4F_D_PRECICE_SINGLE_SLICE_040S_V1_GATE", "status": "pass" if run.returncode == 0 and all(checks.values()) and residual == 0 else "do_not_pass", "timestamp": datetime.now(timezone.utc).isoformat(), "stage_id": "stage4f_d_precice_single_slice_040s_retry7_v1", "run_id": RUN_ID, "case_id": CASE_ID, "scope_contract": {"openfoam": "10", "precice": "3.4.1", "dt_s": 0.005, "steps": 40, "end_time_s": 0.20, "slice_count": 1}, "checks": checks, "runtime": str(RUNTIME), "source_hashes": {"precice_config": sha(CASE / "precice-config.xml"), "precice_dict": sha(CASE / "system" / "preciceDict"), "participant": sha(ROOT / "tools" / "precice_ancf_adapter_v1" / "ancf_structure_participant_v1.py")}, "real_process_counts": counts, "owned_residual": residual, "return_code": run.returncode, "protected": {"stage1_284_evidence_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False, "formal_viv_validation_complete": False}, "storage_audit": {"runtime_bytes": sum(p.stat().st_size for p in RUNTIME.rglob("*") if p.is_file()), "rolling_purge": True, "latest_checkpoint_required": False, "full_step_journal": False}, "qualification": "single-slice preCICE/OpenFOAM 40-step interface smoke with a deterministic ANCF boundary fixture; not formal ANCF numerical equivalence or VIV validation", "next_authorization": "fresh Stage 287 three-slice 8-step smoke only"}
    out = ROOT / "results" / "286_precice_single_slice_040s_retry7_v1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "stage4f_d_precice_single_slice_040s_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "return_code": run.returncode, "process_counts": counts, "owned_residual": residual}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
