from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


class LifecycleError(RuntimeError):
    """Owned process lifecycle failure; callers must not retry the runtime."""


@dataclass
class ProcessIdentity:
    component: str
    pid: int
    creation_time_ns: int
    parent_pid: int
    command_line: list[str]
    cwd: str
    executable: str
    start_time_ns: int
    end_time_ns: int | None = None
    return_code: int | None = None
    owned: bool = True
    cleanup_result: str = "open"

    def close(self, return_code: int | None) -> None:
        self.end_time_ns = time.time_ns(); self.return_code = return_code; self.cleanup_result = "closed"

    def to_dict(self) -> dict[str, Any]: return dict(self.__dict__)


class OwnedProcessRegistry:
    """Exact-PID registry. It never terminates by process name."""

    def __init__(self) -> None:
        self.entries: list[ProcessIdentity] = []

    def register(self, *, component: str, process: Any, command_line: Sequence[str], cwd: Path,
                 executable: str | None = None, creation_time_ns: int | None = None) -> ProcessIdentity:
        pid = int(getattr(process, "pid", 0))
        if pid <= 0: raise LifecycleError("owned process has invalid PID")
        identity = ProcessIdentity(component, pid, int(creation_time_ns or time.time_ns()), os.getpid(), list(command_line),
                                   str(cwd), executable or str(command_line[0]), time.time_ns())
        self.entries.append(identity); return identity

    def close(self, identity: ProcessIdentity, process: Any, *, timeout_s: float = 30.0) -> None:
        if identity not in self.entries or not identity.owned: raise LifecycleError("process is not registered as owned")
        try:
            if getattr(process, "poll", lambda: None)() is None:
                process.terminate(); process.wait(timeout=timeout_s)
            code = getattr(process, "returncode", None)
            identity.close(code)
        except Exception as exc:
            identity.cleanup_result = "cleanup_failed"; raise LifecycleError(str(exc)) from exc

    @property
    def residual(self) -> int:
        return sum(1 for item in self.entries if item.cleanup_result != "closed")

    def audit(self) -> list[dict[str, Any]]: return [item.to_dict() for item in self.entries]


def launch_owned(*, registry: OwnedProcessRegistry, component: str, command: Sequence[str], cwd: Path,
                 launcher: Callable[..., Any] = subprocess.Popen, **kwargs: Any) -> tuple[Any, ProcessIdentity]:
    """Launch exactly one explicitly requested process and register it."""
    process = launcher(list(command), cwd=str(cwd), **kwargs)
    return process, registry.register(component=component, process=process, command_line=command, cwd=cwd)
