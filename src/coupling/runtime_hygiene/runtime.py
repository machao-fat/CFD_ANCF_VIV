from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    import psutil
except ImportError:  # pragma: no cover - the project test environment provides psutil
    psutil = None


RUNTIME_SUBDIRECTORIES = (
    "tmp",
    "logs",
    "requests",
    "responses",
    "checkpoints",
    "python_cache",
    "matlab_pref",
    "matlab_temp",
    "matlab_logs",
    "openfoam_temp",
    "process_registry",
    "environment_audit",
)


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:10]


def _require_d_drive(path: Path) -> Path:
    resolved = path.resolve()
    if os.name == "nt" and resolved.drive.upper() != "D:":
        raise ValueError(f"runtime path must be on D:, got {resolved}")
    return resolved


def create_runtime_run(project_root: str | Path, task_name: str, run_id: str | None = None) -> Path:
    root = _require_d_drive(Path(project_root)) / "runtime" / task_name
    run = root / (run_id or _utc_run_id())
    if run.exists():
        raise FileExistsError(f"runtime run already exists: {run}")
    run.mkdir(parents=True, exist_ok=False)
    for name in RUNTIME_SUBDIRECTORIES:
        (run / name).mkdir()
    return run


def build_task_environment(run_dir: str | Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    run = _require_d_drive(Path(run_dir))
    env = dict(os.environ if base is None else base)
    env.update(
        {
            "TEMP": str(run / "tmp"),
            "TMP": str(run / "tmp"),
            "TMPDIR": str(run / "tmp"),
            "PYTHONPYCACHEPREFIX": str(run / "python_cache"),
            "PIP_CACHE_DIR": str(run / "python_cache" / "pip"),
            "MPLCONFIGDIR": str(run / "python_cache" / "matplotlib"),
            "MATLAB_PREFDIR": str(run / "matlab_pref"),
        }
    )
    for key in ("TEMP", "TMP", "TMPDIR", "PYTHONPYCACHEPREFIX", "PIP_CACHE_DIR", "MPLCONFIGDIR", "MATLAB_PREFDIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def probe_python_runtime() -> dict[str, Any]:
    temp = Path(tempfile.gettempdir()).resolve()
    return {
        "tempfile_gettempdir": str(temp),
        "drive": temp.drive,
        "is_d_drive": temp.drive.upper() == "D:" if os.name == "nt" else True,
        "pid": os.getpid(),
    }


def inventory_processes() -> list[dict[str, Any]]:
    if psutil is None:
        return []
    rows: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = process.info
            rows.append(
                {
                    "pid": int(info["pid"]),
                    "parent_pid": int(info.get("ppid") or 0),
                    "creation_time": float(info.get("create_time") or 0.0),
                    "name": info.get("name") or "",
                    "executable": info.get("exe") or "",
                    "command_line": list(info.get("cmdline") or []),
                    "cwd": _process_cwd(process),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(rows, key=lambda row: row["pid"])


def _process_cwd(process: Any) -> str:
    try:
        return str(process.cwd())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return ""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
