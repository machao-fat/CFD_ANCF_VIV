from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from src.coupling.persistent_ancf import PersistentANCFRunner
from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run
from .evidence import EventLog, ProcessEvidence, canonical_sha256, file_sha256, process_snapshot, validate_event_log


def matlab_worker_command(*, matlab_exe: str | Path, log_path: str | Path, token: str, request_dir: Path) -> list[str]:
    root = Path(__file__).resolve().parents[3]
    worker_root = root / "src" / "coupling" / "persistent_ancf_matlab"
    ancf_root = root / "src" / "structure_ancf_matlab"
    quote = lambda value: str(value.resolve()).replace("\\", "/").replace("'", "''")
    expression = (
        f"setenv('CFD_ANCF_RUN_TOKEN','{token}'); "
        f"addpath(genpath('{quote(worker_root)}')); "
        f"persistent_ancf_worker('{quote(request_dir)}','{quote(ancf_root)}','{quote(worker_root)}')"
    )
    return [str(Path(matlab_exe).resolve()), "-wait", "-logfile", str(Path(log_path).resolve()), "-batch", expression]


class RealRunnerSession:
    """A real R2021b runner plus an event-chain-owned process audit."""

    records: list[dict[str, Any]] = []

    def __init__(self, *, project_root: str | Path, config: Mapping[str, Any], matlab_exe: str | Path, purpose: str, runtime_task: str = "stage4e_b1_v3_1") -> None:
        self.project_root = Path(project_root).resolve()
        self.root = create_runtime_run(self.project_root, runtime_task)
        self.run_id = self.root.name
        self.run_token = f"r2021b_{self.run_id}_{uuid.uuid4().hex}"
        self.log_path = self.root / "logs" / "matlab_internal.log"
        self.console_log_path = self.root / "logs" / "launcher_console.log"
        self.event_log = EventLog(self.root / "logs" / "raw_event_log.jsonl", run_id=self.run_id, run_token=self.run_token)
        self.evidence = ProcessEvidence(self.event_log, run_dir=self.root, run_token=self.run_token)
        base = dict(os.environ)
        base["CFD_ANCF_MATLAB_EXE"] = str(Path(matlab_exe).resolve())
        self.environment = build_task_environment(self.root, base)
        self.command = matlab_worker_command(matlab_exe=matlab_exe, log_path=self.log_path, token=self.run_token, request_dir=self.root)
        self.runner = PersistentANCFRunner(
            config=config,
            matlab_exe=matlab_exe,
            request_dir=self.root,
            timeout_s=180.0,
            launch_command=self.command,
            process_environment=self.environment,
            console_log_path=self.console_log_path,
        )
        self.purpose = purpose
        self.closed = False
        self.evidence.start()
        self.event_log.append("runner_session_created", purpose=purpose, log_path=self.log_path, payload={"command": self.command, "config_sha256": canonical_sha256(dict(config))})

    def close(self) -> dict[str, Any]:
        if self.closed:
            return self.summary
        error: str | None = None
        try:
            self.runner.shutdown()
        except Exception as exc:  # evidence must still be closed
            error = f"{type(exc).__name__}: {exc}"
            self.event_log.append("runner_shutdown_error", purpose=self.purpose, log_path=self.log_path, payload={"error": error})
        self.evidence.stop()
        actions = self.evidence.cleanup(timeout_s=10.0)
        rows = self.evidence.snapshot_records()
        residual = []
        for row in rows:
            if process_snapshot(int(row["pid"]), purpose=row.get("purpose", "owned"), log_path=row.get("log_path")) is not None:
                residual.append(int(row["pid"]))
        audit = validate_event_log(self.event_log.path)
        self.summary = {
            "run_id": self.run_id,
            "run_token": self.run_token,
            "runtime_root": str(self.root),
            "purpose": self.purpose,
            "command": self.command,
            "internal_log_path": str(self.log_path),
            "launcher_console_log_path": str(self.console_log_path),
            "event_log_path": str(self.event_log.path),
            "event_log_sha256": audit.get("sha256"),
            "event_log_audit": audit,
            "process_records": rows,
            "cleanup_actions": actions,
            "owned_residual_pids": residual,
            "owned_residual_count": len(residual),
            "unrelated_terminated": 0,
            "shutdown_error": error,
            "runner_start_count": self.runner.start_count,
        }
        (self.root / "process_registry" / "session_summary.json").write_text(json.dumps(self.summary, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        RealRunnerSession.records.append(self.summary)
        self.closed = True
        return self.summary
