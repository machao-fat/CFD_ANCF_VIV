from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


class EventLog:
    REQUIRED = (
        "sequence", "timestamp_utc", "monotonic_time_s", "event_type", "run_id", "run_token",
        "pid", "parent_pid", "creation_time", "executable", "executable_sha256", "command_line",
        "command_line_sha256", "cwd", "purpose", "log_path", "exit_code", "cleanup_action", "payload_sha256",
    )

    def __init__(self, path: str | Path, *, run_id: str, run_token: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.run_token = run_token
        self.sequence = 0
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []

    def append(
        self,
        event_type: str,
        *,
        process: Mapping[str, Any] | None = None,
        purpose: str = "controller",
        log_path: str | Path | None = None,
        exit_code: int | None = None,
        cleanup_action: str | None = None,
        payload: Any = None,
    ) -> dict[str, Any]:
        process = dict(process or {})
        command_line = list(process.get("command_line") or [])
        payload_hash = canonical_sha256(payload) if payload is not None else None
        record = {
            # The sequence is assigned while holding the write lock below.
            # ProcessEvidence and the controller can append concurrently.
            "sequence": None,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_time_s": time.monotonic(),
            "event_type": str(event_type),
            "run_id": self.run_id,
            "run_token": self.run_token,
            "pid": process.get("pid"),
            "parent_pid": process.get("parent_pid"),
            "creation_time": process.get("creation_time"),
            "executable": process.get("executable"),
            "executable_sha256": process.get("executable_sha256"),
            "command_line": command_line,
            "command_line_sha256": canonical_sha256(command_line),
            "cwd": process.get("cwd"),
            "purpose": purpose or process.get("purpose"),
            "log_path": str(log_path or process.get("log_path") or ""),
            "exit_code": exit_code,
            "cleanup_action": cleanup_action,
            "payload_sha256": payload_hash,
        }
        with self._lock:
            record["sequence"] = self.sequence
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.records.append(record)
            self.sequence += 1
        return record

    def sha256(self) -> str:
        value = file_sha256(self.path)
        if value is None:
            raise FileNotFoundError(self.path)
        return value


def _process_row(process: Any, *, purpose: str, log_path: str | Path | None = None) -> dict[str, Any]:
    info = getattr(process, "info", {}) or {}
    pid = int(info.get("pid") or process.pid)
    try:
        ppid = int(info.get("ppid") or process.ppid())
    except Exception:
        ppid = int(info.get("ppid") or 0)
    try:
        creation = float(info.get("create_time") or process.create_time())
    except Exception:
        creation = None
    executable = str(info.get("exe") or "")
    if not executable:
        try:
            executable = process.exe()
        except Exception:
            executable = ""
    command_line = list(info.get("cmdline") or [])
    if not command_line:
        try:
            command_line = list(process.cmdline())
        except Exception:
            command_line = []
    try:
        cwd = str(process.cwd())
    except Exception:
        cwd = ""
    return {
        "pid": pid,
        "parent_pid": ppid,
        "creation_time": creation,
        "executable": executable,
        "executable_sha256": file_sha256(executable) if executable else None,
        "command_line": command_line,
        "cwd": cwd,
        "purpose": purpose,
        "log_path": str(log_path or ""),
    }


def process_snapshot(pid: int, *, purpose: str, log_path: str | Path | None = None) -> dict[str, Any] | None:
    if psutil is None:
        return None
    try:
        return _process_row(psutil.Process(int(pid)), purpose=purpose, log_path=log_path)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def enumerate_matlab_processes() -> list[dict[str, Any]]:
    if psutil is None:
        return []
    rows = []
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        try:
            name = Path(str(process.info.get("name") or "")).name.lower()
            exe = Path(str(process.info.get("exe") or "")).name.lower()
            if name.startswith("matlab") or exe.startswith("matlab"):
                rows.append(_process_row(process, purpose="preflight_matlab_inventory"))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(rows, key=lambda row: (row["pid"], row.get("creation_time") or 0.0))


class ProcessEvidence:
    """Live process-tree recorder with PID/creation/token/cwd identity checks."""

    def __init__(self, event_log: EventLog, *, run_dir: str | Path, run_token: str, poll_s: float = 0.05) -> None:
        self.event_log = event_log
        self.run_dir = Path(run_dir).resolve()
        self.run_token = run_token
        self.poll_s = poll_s
        self.records: dict[tuple[int, float], dict[str, Any]] = {}
        self._root_pids: set[int] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cleanup_completed = False

    def register_pid(self, pid: int, *, purpose: str, log_path: str | Path | None = None) -> dict[str, Any] | None:
        row = process_snapshot(pid, purpose=purpose, log_path=log_path)
        if row is None:
            return None
        key = (int(row["pid"]), float(row["creation_time"] or 0.0))
        self.records[key] = row
        self._root_pids.add(int(row["pid"]))
        self.event_log.append("process_registered", process=row, purpose=purpose, log_path=log_path, payload={"identity": key})
        return row

    def _same_identity(self, row: Mapping[str, Any]) -> bool:
        if psutil is None or row.get("creation_time") is None:
            return False

    def _identity_state(self, row: Mapping[str, Any]) -> str:
        """Return a cleanup-safe state without conflating exit and mismatch."""
        if psutil is None or row.get("creation_time") is None:
            return "verified"
        try:
            process = psutil.Process(int(row["pid"]))
        except psutil.NoSuchProcess:
            return "already_exited"
        except psutil.AccessDenied:
            return "access_denied"
        except psutil.ZombieProcess:
            return "already_exited"
        try:
            if abs(float(process.create_time()) - float(row["creation_time"])) >= 1e-3:
                return "identity_mismatch"
        except psutil.AccessDenied:
            return "access_denied"
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return "already_exited"
        return "verified"
        try:
            process = psutil.Process(int(row["pid"]))
            return abs(float(process.create_time()) - float(row["creation_time"])) < 1e-3
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def _under_run(self, cwd: str) -> bool:
        try:
            Path(cwd).resolve().relative_to(self.run_dir)
            return True
        except (OSError, ValueError):
            return False

    def _token_match(self, command_line: Iterable[str]) -> bool:
        # Match one complete argv token.  Prefix/substring matching would let
        # a same-cwd process using ``run_token + '_other'`` become owned.
        return any(str(item) == self.run_token for item in command_line)

    def _is_owned_candidate(self, row: Mapping[str, Any]) -> bool:
        if self._token_match(row.get("command_line") or []):
            return True
        if self._under_run(str(row.get("cwd") or "")):
            return self._has_owned_ancestor(int(row["pid"]))
        return False

    def _has_owned_ancestor(self, pid: int) -> bool:
        if psutil is None:
            return False
        current_pid = int(pid)
        seen: set[int] = set()
        for _ in range(16):
            if current_pid in self._root_pids:
                return True
            if current_pid in seen or current_pid <= 0:
                return False
            seen.add(current_pid)
            try:
                current_pid = int(psutil.Process(current_pid).ppid())
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                return False
        return False

    def scan_once(self) -> None:
        if psutil is None:
            return
        candidates: dict[int, Any] = {}
        for root_pid in list(self._root_pids):
            try:
                root = psutil.Process(int(root_pid))
                candidates[root.pid] = root
                for child in root.children(recursive=True):
                    candidates[child.pid] = child
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        # Avoid calling cwd()/exe() for every process on Windows.  The global
        # pass only needs exact token-bearing argv entries; descendants of the
        # registered roots are already included above.
        for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
            try:
                if self._token_match(process.info.get("cmdline") or []):
                    candidates[process.pid] = process
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        for process in candidates.values():
            try:
                row = _process_row(process, purpose="owned_process_observation")
                if not self._is_owned_candidate(row):
                    continue
                key = (int(row["pid"]), float(row["creation_time"] or 0.0))
                if key not in self.records:
                    self.records[key] = row
                    self.event_log.append("process_started", process=row, purpose=row["purpose"], log_path=row.get("log_path"), payload={"identity": key})
                else:
                    self.records[key].update({"parent_pid": row["parent_pid"], "command_line": row["command_line"], "cwd": row["cwd"]})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.scan_once()
            time.sleep(self.poll_s)
        self.scan_once()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name=f"process-evidence-{self.run_token[:8]}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def snapshot_records(self) -> list[dict[str, Any]]:
        return [dict(value) for value in sorted(self.records.values(), key=lambda row: (row["pid"], row.get("creation_time") or 0.0))]

    def safe_to_cleanup(self, row: Mapping[str, Any], *, owned_pids: set[int]) -> tuple[bool, str]:
        identity_state = self._identity_state(row)
        if identity_state == "already_exited":
            return False, "process_gone"
        if identity_state == "identity_mismatch":
            return False, "creation_time_mismatch"
        if identity_state == "access_denied":
            return False, "access_denied"
        token_match = self._token_match(row.get("command_line") or [])
        cwd_match = self._under_run(str(row.get("cwd") or ""))
        if not token_match and not cwd_match:
            return False, "run_token_and_cwd_mismatch"
        try:
            current = psutil.Process(int(row["pid"]))
            parent = int(current.ppid())
            recorded = int(row.get("parent_pid") or -1)
            if parent == recorded or parent in owned_pids:
                return True, "identity_verified"
            if token_match and cwd_match:
                return True, "identity_verified_reparented_token"
            if parent != recorded and parent not in owned_pids:
                return False, "parent_relation_mismatch"
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False, "process_gone_or_access_denied"
        return True, "identity_verified"

    def cleanup(self, *, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        if self._cleanup_completed:
            return []
        self.scan_once()
        records = self.snapshot_records()
        owned_pids = {int(row["pid"]) for row in records}
        actions: list[dict[str, Any]] = []
        def depth(row: Mapping[str, Any]) -> int:
            current = int(row.get("parent_pid") or -1)
            value = 0
            seen = set()
            while current in owned_pids and current not in seen:
                seen.add(current)
                value += 1
                parent_row = next((candidate for candidate in records if int(candidate["pid"]) == current), None)
                current = int(parent_row.get("parent_pid") or -1) if parent_row else -1
            return value
        for row in sorted(records, key=depth, reverse=True):
            allowed, reason = self.safe_to_cleanup(row, owned_pids=owned_pids)
            if not allowed:
                if reason == "process_gone":
                    action = "already_exited"
                elif reason == "access_denied":
                    action = "cleanup_blocked_access_denied"
                else:
                    action = "refused_identity_mismatch"
                actions.append({"pid": row["pid"], "creation_time": row.get("creation_time"), "action": action, "reason": reason})
                self.event_log.append("cleanup_action", process=row, purpose=row.get("purpose", "owned"), log_path=row.get("log_path"), cleanup_action=action, payload={"pid": row["pid"], "reason": reason})
                continue
            try:
                process = psutil.Process(int(row["pid"]))
                if process.is_running():
                    process.terminate()
                    try:
                        process.wait(timeout=timeout_s)
                    except psutil.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=timeout_s)
                        action = "kill_after_timeout"
                    else:
                        action = "terminate"
                else:
                    action = "already_gone"
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                action = "already_gone"
            except (psutil.AccessDenied, psutil.TimeoutExpired) as exc:
                action = f"cleanup_failed:{type(exc).__name__}"
            actions.append({"pid": row["pid"], "creation_time": row.get("creation_time"), "action": action})
            self.event_log.append("cleanup_action", process=row, purpose=row.get("purpose", "owned"), log_path=row.get("log_path"), cleanup_action=action, payload={"pid": row["pid"], "action": action})
        self._cleanup_completed = True
        return actions


def validate_event_log(path: str | Path) -> dict[str, Any]:
    rows = []
    errors: list[str] = []
    target = Path(path)
    try:
        with target.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream):
                if not line.endswith("\n"):
                    errors.append(f"line_{line_number}_not_newline_terminated")
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"line_{line_number}_json:{exc}")
                    continue
                rows.append(row)
                missing = [key for key in EventLog.REQUIRED if key not in row]
                errors.extend(f"line_{line_number}_missing:{key}" for key in missing)
                if row.get("sequence") != line_number:
                    errors.append(f"line_{line_number}_sequence:{row.get('sequence')}")
    except OSError as exc:
        errors.append(f"read:{exc}")
    return {
        "status": "passed" if not errors and bool(rows) else "failed",
        "event_count": len(rows),
        "sequence_continuous": not any("sequence:" in item for item in errors),
        "required_fields_complete": not any("missing:" in item for item in errors),
        "errors": errors,
        "sha256": file_sha256(target),
    }
