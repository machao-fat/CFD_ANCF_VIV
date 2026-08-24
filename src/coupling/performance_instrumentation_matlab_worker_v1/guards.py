from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .protocol import ProtocolError


@dataclass(frozen=True)
class OwnedProcess:
    pid: int
    parent_pid: int | None
    owned: bool = True
    closed: bool = False


class OwnedProcessRegistry:
    """Offline ownership model used to prove precise, non-name-based cleanup."""

    def __init__(self) -> None:
        self.processes: dict[int, OwnedProcess] = {}

    def register(self, pid: int, *, parent_pid: int | None = None, owned: bool = True) -> None:
        if pid in self.processes:
            raise ProtocolError(f"duplicate pid {pid}")
        self.processes[pid] = OwnedProcess(pid, parent_pid, owned, False)

    def cleanup_owned_tree(self, root_pid: int) -> dict[str, object]:
        if root_pid not in self.processes or not self.processes[root_pid].owned:
            raise ProtocolError("cleanup root is not an owned process")
        targets = {root_pid}
        changed = True
        while changed:
            changed = False
            for process in self.processes.values():
                if process.owned and process.parent_pid in targets and process.pid not in targets:
                    targets.add(process.pid); changed = True
        for pid in targets:
            item = self.processes[pid]
            self.processes[pid] = OwnedProcess(item.pid, item.parent_pid, item.owned, True)
        residual = sum(1 for item in self.processes.values() if item.owned and not item.closed)
        non_owned_closed = any((not item.owned) and item.closed for item in self.processes.values())
        return {"root_pid": root_pid, "closed_owned_pids": sorted(targets), "residual": residual,
                "non_owned_closed": non_owned_closed}


def validate_runtime_scope(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if resolved.drive.upper() != "D:":
        raise ProtocolError("runtime must be on D drive")
    if "performance_instrumentation_matlab_worker_v1" not in str(resolved):
        raise ProtocolError("runtime is outside isolated Stage93 scope")
    return resolved


def no_real_process_start(counter: dict[str, int]) -> None:
    forbidden = {name: int(counter.get(name, 0)) for name in ("MATLAB", "OpenFOAM", "WSL", "CFD")}
    if any(forbidden.values()):
        raise ProtocolError(f"forbidden real process start: {forbidden}")


def reject_old_artifact(*, artifact_path: str | Path, allowed_runtime: str | Path) -> None:
    artifact = Path(artifact_path).resolve()
    allowed = Path(allowed_runtime).resolve()
    if allowed not in artifact.parents:
        raise ProtocolError("old or foreign runtime artifact reuse is forbidden")


def restart_state_after_windows_restart() -> str:
    """A restart never resumes an old contract; the only state is idle."""
    return "IDLE_WAITING_FOR_CONTRACT"
