"""Record safe cleanup of a launcher orphan identified after the diagnostic."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_orphan_cleanup(runtime_root: str | Path, *, pid: int, creation_time: float, executable: str, command_line: list[str], cwd: str, action: str) -> dict[str, Any]:
    root = Path(runtime_root).resolve()
    record = {
        "schema": "stage4f-c-environment-repair-v1-orphan-cleanup-1.0.0",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pid": pid,
        "creation_time": creation_time,
        "executable": executable,
        "command_line": command_line,
        "cwd": cwd,
        "identity_basis": "exact diagnostic run token and runtime cwd in -r command line",
        "action": action,
        "post_cleanup_alive": False,
    }
    path = root / "logs" / "orphan_cleanup_record.json"
    path.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return record
