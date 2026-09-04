from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class StorageError(ValueError):
    pass


class RollingStore:
    """Atomic latest-state store; journals remain append-only and complete."""

    def __init__(self, root: str | Path, *, retention: int = 1):
        self.root = Path(root)
        if retention < 1:
            raise StorageError("retention must be positive")
        self.retention = retention
        for name in ("checkpoint", "restart", "force", "journal"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")

    def _atomic_json(self, path: Path, value: Any) -> str:
        raw = self._canonical(value)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        return hashlib.sha256(raw).hexdigest()

    def write_latest(self, category: str, value: Any, *, step: int) -> dict[str, Any]:
        if category not in ("checkpoint", "restart", "force") or step < 0:
            raise StorageError("invalid rolling category or step")
        path = self.root / category / "latest.json"
        digest = self._atomic_json(path, {"step": step, "value": value})
        return {"path": str(path), "step": step, "sha256": digest, "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}

    def append_journal(self, record: dict[str, Any]) -> None:
        raw = self._canonical(record)
        path = self.root / "journal" / "steps.jsonl"
        with path.open("ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def audit(self) -> dict[str, Any]:
        files = [p for p in self.root.rglob("*") if p.is_file()]
        journal = self.root / "journal" / "steps.jsonl"
        records = 0
        if journal.is_file():
            with journal.open(encoding="utf-8") as stream:
                records = sum(1 for line in stream if line.strip())
        return {"root": str(self.root), "latest_present": all((self.root / name / "latest.json").is_file() for name in ("checkpoint", "restart", "force")), "journal_records": records, "file_count": len(files), "bytes": sum(p.stat().st_size for p in files)}
