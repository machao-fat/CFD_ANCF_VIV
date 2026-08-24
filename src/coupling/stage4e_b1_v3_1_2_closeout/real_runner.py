from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from src.coupling.stage4e_b1_v3_1_1_closeout.real_runner import RealRunnerSession as _BaseRealRunnerSession


class RealRunnerSession(_BaseRealRunnerSession):
    """v3.1.2 session with one lifecycle entry point and owned evidence."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        config: Mapping[str, Any],
        matlab_exe: str | Path,
        purpose: str,
        runtime_task: str = "stage4e_b1_v3_1_2",
    ) -> None:
        super().__init__(
            project_root=project_root,
            config=config,
            matlab_exe=matlab_exe,
            purpose=purpose,
            runtime_task=runtime_task,
        )
        self.started = False
        self.start_invocation_count = 0
        self.start_result: dict[str, Any] | None = None
        matlab_log_dir = str((self.root / "logs").resolve())
        self.environment["MATLAB_LOG_DIR"] = matlab_log_dir
        self.runner.process_environment["MATLAB_LOG_DIR"] = matlab_log_dir

    def start(self) -> dict[str, Any]:
        """Start exactly once through the session, never by test-side bypass."""
        self.start_invocation_count += 1
        if self.closed:
            raise RuntimeError("cannot start a closed RealRunnerSession")
        if self.started:
            self.event_log.append(
                "session_start_idempotent",
                purpose=self.purpose,
                log_path=self.log_path,
                payload={"start_invocation_count": self.start_invocation_count},
            )
            return dict(self.start_result or {})
        self.event_log.append(
            "session_start_requested",
            purpose=self.purpose,
            log_path=self.log_path,
            payload={"start_invocation_count": self.start_invocation_count},
        )
        try:
            self.start_result = self.runner.start()
            launcher_pid = self.runner.worker_pid
            if launcher_pid is None:
                raise RuntimeError("runner returned without a launcher PID")
            registered = self.evidence.register_pid(
                launcher_pid,
                purpose="matlab_worker_launcher",
                log_path=self.console_log_path,
            )
            if registered is None:
                raise RuntimeError("launcher PID could not be registered in ProcessEvidence")
            self.evidence.scan_once()
            self.event_log.append(
                "session_started",
                purpose=self.purpose,
                log_path=self.log_path,
                payload={
                    "launcher_pid": launcher_pid,
                    "runner_start_count": self.runner.start_count,
                    "owned_process_records": self.runner.owned_process_records,
                },
            )
            self.started = True
            return dict(self.start_result)
        except BaseException as exc:
            self.event_log.append(
                "session_start_failed",
                purpose=self.purpose,
                log_path=self.log_path,
                payload={"error_type": type(exc).__name__, "error": str(exc)},
            )
            try:
                self.close()
            finally:
                raise

    def close(self) -> dict[str, Any]:
        summary = super().close()
        summary.update(
            {
                "session_start_invocation_count": self.start_invocation_count,
                "session_started": self.started,
                "runner_owned_process_records": self.runner.owned_process_records,
                "runner_cleanup_audit": self.runner.cleanup_audit,
            }
        )
        summary_path = self.root / "process_registry" / "session_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        return summary
