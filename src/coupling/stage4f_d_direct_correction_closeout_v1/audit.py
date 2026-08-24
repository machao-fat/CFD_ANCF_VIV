from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_mat_state(path: Path) -> dict[str, Any]:
    import scipy.io

    loaded = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)
    state = loaded["state"]
    fields: dict[str, dict[str, Any]] = {}
    all_finite = True
    aliases = {"q": "q", "qdot": "qd", "qddot": "qdd"}
    for name, stored_name in aliases.items():
        values = list(getattr(state, stored_name).flat) if hasattr(state, stored_name) else []
        finite = bool(values) and all(math.isfinite(float(value)) for value in values)
        fields[name] = {"count": len(values), "finite": finite}
        all_finite = all_finite and finite
    return {"fields": fields, "all_finite": all_finite}


def closeout(runtime_run: Path) -> dict[str, Any]:
    source = runtime_run / "replay" / "input" / "committed_step527.mat"
    output = runtime_run / "replay_once" / "output" / "correction_step528.mat"
    stderr = runtime_run / "replay_once" / "stderr.log"
    stdout = runtime_run / "replay_once" / "stdout.log"
    matlab_log = runtime_run / "replay_once" / "matlab.log"
    state = audit_mat_state(output) if output.is_file() else {"fields": {}, "all_finite": False}
    return {
        "schema": "stage4f-d-direct-correction-closeout-v1",
        "runtime_run": str(runtime_run.resolve()),
        "source": {"path": str(source.resolve()), "exists": source.is_file(), "sha256": sha256(source) if source.is_file() else None, "size": source.stat().st_size if source.is_file() else None},
        "output": {"path": str(output.resolve()), "exists": output.is_file(), "sha256": sha256(output) if output.is_file() else None, "size": output.stat().st_size if output.is_file() else None, "mtime_ns": output.stat().st_mtime_ns if output.is_file() else None, "state": state},
        "logs": {"stdout": str(stdout.resolve()), "stdout_size": stdout.stat().st_size if stdout.is_file() else None, "stderr": str(stderr.resolve()), "stderr_size": stderr.stat().st_size if stderr.is_file() else None, "matlab_log": str(matlab_log.resolve()), "matlab_log_size": matlab_log.stat().st_size if matlab_log.is_file() else None},
        "matlab_return_code": None,
        "return_code_evidence_status": "unavailable_wrapper_failed_before_persistence",
        "matlab_output_status": "generated_finite" if output.is_file() and state["all_finite"] else "invalid_or_missing",
        "wrapper_failure": "results_directory_missing",
        "openfoam_started": 0,
        "wsl_started": 0,
        "cfd_started": 0,
        "owned_residual": 0,
        "gate": "do_not_pass",
        "terminal": "technical_output_valid_transaction_evidence_incomplete",
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
