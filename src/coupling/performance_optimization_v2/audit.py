from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Iterable


class AuditError(RuntimeError):
    """Audit artifact could not be committed or was incomplete."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class BatchAuditWriter:
    """Batch only verbose audit events; final artifacts are always separate."""

    def __init__(self, root: Path, *, batch_size: int = 16) -> None:
        if batch_size <= 0: raise AuditError("batch_size must be positive")
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True); self.batch_size = int(batch_size)
        self.pending: list[dict[str, Any]] = []; self.flush_count = 0; self.next_sequence = 1; self.closed = False

    def append(self, event: dict[str, Any]) -> None:
        if self.closed: raise AuditError("audit writer is closed")
        event = dict(event); event.setdefault("audit_sequence", self.next_sequence); self.next_sequence += 1
        self.pending.append(event)
        if len(self.pending) >= self.batch_size: self.flush()

    def flush(self) -> Path | None:
        if not self.pending: return None
        path = self.root / "events.jsonl"; temporary = self.root / f"events.{os.getpid()}.{time.time_ns()}.tmp"
        previous = path.read_bytes() if path.is_file() else b""
        encoded = b"".join(_canonical(item) for item in self.pending)
        temporary.write_bytes(previous + encoded); os.replace(temporary, path)
        self.pending.clear(); self.flush_count += 1; return path

    def finalize(self, *, checkpoint: dict[str, Any], raw_snapshot: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
        if self.closed: raise AuditError("audit writer already finalized")
        self.flush()
        artifacts = {"checkpoint": self.root / "checkpoint_final.json", "raw_snapshot": self.root / "raw_snapshot_final.json", "gate": self.root / "gate.json"}
        for key, value in (("checkpoint", checkpoint), ("raw_snapshot", raw_snapshot), ("gate", gate)):
            if not isinstance(value, dict) or value.get("committed") is False: raise AuditError(f"invalid final {key}")
            target = artifacts[key]; temporary = target.with_suffix(".tmp"); temporary.write_bytes(_canonical(value)); os.replace(temporary, target)
        self.closed = True
        return {key: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size} for key, path in artifacts.items()}


def disk_usage_bytes(root: Path) -> int:
    """Return regular-file bytes without following links or building a Path tree.

    Benchmark runtimes contain thousands of small bridge artifacts.  The
    previous ``Path.rglob`` implementation allocated a Path object and then
    performed a second stat for every entry, making the final read-only
    resource audit a measurable part of a short 40-step wall clock.  An
    explicit DirEntry walk preserves the same byte accounting while avoiding
    symlink traversal and redundant metadata work.
    """
    total = 0
    pending = [Path(root)]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    total += int(entry.stat(follow_symlinks=False).st_size)
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
    return total


def resource_snapshot(root: Path, *, process_ids: Iterable[int] = ()) -> dict[str, Any]:
    result = {"timestamp_ns": time.time_ns(), "disk_bytes": disk_usage_bytes(root), "cpu_percent": None, "memory_bytes": None, "processes": []}
    try:
        import psutil
        process = psutil.Process(os.getpid()); result["cpu_percent"] = process.cpu_percent(None); result["memory_bytes"] = process.memory_info().rss
        for pid in process_ids:
            try:
                item = psutil.Process(int(pid)); result["processes"].append({"pid": int(pid), "cpu_percent": item.cpu_percent(None), "memory_bytes": item.memory_info().rss})
            except psutil.Error: result["processes"].append({"pid": int(pid), "unavailable": True})
    except ImportError: pass
    return result
