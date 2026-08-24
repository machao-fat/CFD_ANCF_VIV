from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MATLAB = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
SOURCE = ROOT / "runtime" / "stage4f_d_e5_matlab_worker_probe_replay_v1" / "replay" / "input" / "committed_step527.mat"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def matlab_quote(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def finite_state(path: Path) -> dict[str, Any]:
    import scipy.io

    state = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)["state"]
    fields: dict[str, Any] = {}
    passed = True
    for public, stored in {"q": "q", "qdot": "qd", "qddot": "qdd"}.items():
        values = list(getattr(state, stored).flat) if hasattr(state, stored) else []
        finite = bool(values) and all(math.isfinite(float(value)) for value in values)
        fields[public] = {"count": len(values), "finite": finite}
        passed = passed and finite
    return {"fields": fields, "all_finite": passed}


def run_once() -> dict[str, Any]:
    run_id = f"direct_correction_v2_{utc().replace(':', '').replace('-', '').replace('.', '')}_{uuid.uuid4().hex[:10]}"
    runtime = ROOT / "runtime" / "stage4f_d_direct_correction_probe_v2" / run_id
    results = ROOT / "results" / "71_stage4f_d_direct_correction_probe_v2" / run_id
    input_dir, output_dir, logs = runtime / "input", runtime / "output", runtime / "logs"
    for path in (input_dir, output_dir, logs, results):
        path.mkdir(parents=True, exist_ok=False)
    source_copy = input_dir / "committed_step527.mat"
    shutil.copy2(SOURCE, source_copy)
    if sha256(source_copy) != sha256(SOURCE):
        raise RuntimeError("source copy hash mismatch")
    output = output_dir / "correction_step528.mat"
    stdout_path, stderr_path, matlab_log = logs / "stdout.log", logs / "stderr.log", logs / "matlab.log"
    env = dict(os.environ)
    for key, folder in {"TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmpdir", "PREFDIR": "pref", "MATLAB_PREFDIR": "pref", "PYTHONPYCACHEPREFIX": "pycache"}.items():
        path = runtime / folder
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    forces = "[10598.827521479765 80.057248021457667 3.0496911730762615e-10;5942.713889383147 45.031168824975289 -6.9643709246151237e-11;11127.242948420422 93.125913897838089 -1.721296496848751e-10]"
    expression = (
        f"addpath(genpath('{matlab_quote(ROOT / 'src' / 'structure_ancf_matlab')}'));"
        f"S=load('{matlab_quote(source_copy)}','state');state=S.state;"
        f"state.model.time.dt=0.00125;state=ancf_advance_step(state,{forces},0.00125);"
        f"save('{matlab_quote(output)}','state','-v7');"
    )
    command = [str(MATLAB), "-batch", expression, "-logfile", str(matlab_log)]
    start_ns = time.time_ns()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=runtime, env=env, stdout=stdout, stderr=stderr, text=True, shell=False)
        launch = {"run_id": run_id, "pid": process.pid, "parent_pid": os.getpid(), "start_time_ns": start_ns, "command": command, "cwd": str(runtime), "executable": str(MATLAB), "executable_sha256": sha256(MATLAB), "environment": {key: env[key] for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR")}}
        atomic_json(results / "process_launch.json", launch)
        timed_out = False
        try:
            return_code = process.wait(timeout=300)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                return_code = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=30)
    exit_record = {**launch, "end_time_ns": time.time_ns(), "return_code": return_code, "timeout": timed_out, "closed": process.poll() is not None, "owned_residual": int(process.poll() is None)}
    atomic_json(results / "process_exit.json", exit_record)
    output_state = finite_state(output) if output.is_file() else {"fields": {}, "all_finite": False}
    artifact = {"source_path": str(source_copy), "source_sha256": sha256(source_copy), "output_path": str(output), "output_exists": output.is_file(), "output_sha256": sha256(output) if output.is_file() else None, "output_size": output.stat().st_size if output.is_file() else None, "output_mtime_ns": output.stat().st_mtime_ns if output.is_file() else None, "state": output_state, "identity": {"step": 528, "time_s": 2.16875, "tick": 2168750000}}
    atomic_json(results / "artifact_audit.json", artifact)
    passed = return_code == 0 and not timed_out and artifact["output_exists"] and output_state["all_finite"] and exit_record["owned_residual"] == 0
    gate = {"STAGE4F_D_DIRECT_CORRECTION_PROBE_V2_GATE": "pass" if passed else "do_not_pass", "run_id": run_id, "return_code": return_code, "timeout": timed_out, "output_status": "generated_finite" if artifact["output_exists"] and output_state["all_finite"] else "invalid_or_missing", "owned_residual": exit_record["owned_residual"], "openfoam_started": 0, "wsl_started": 0, "cfd_started": 0, "E5_B_STATUS": "not_started"}
    atomic_json(results / "gate.json", gate)
    return {"runtime": str(runtime), "results": str(results), "gate": gate, "artifact": artifact}


if __name__ == "__main__":
    print(json.dumps(run_once(), ensure_ascii=False, allow_nan=False))
