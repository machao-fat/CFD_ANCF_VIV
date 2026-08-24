"""Validation helpers for complete, creation-time-bound owned process evidence."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

REQUIRED_FIELDS = ("pid", "creation_time", "parent_pid", "executable", "command_line", "cwd",
                   "start_timestamp", "end_timestamp", "return_code", "log_path", "shutdown_method", "ownership_basis")


def validate_process_record(record: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_FIELDS if key not in record or record[key] in (None, "", [])]
    invalid = []
    if "pid" in record and int(record["pid"]) <= 0:
        invalid.append("pid")
    if "parent_pid" in record and int(record["parent_pid"]) <= 0:
        invalid.append("parent_pid")
    if "creation_time" in record and (not math.isfinite(float(record["creation_time"])) or float(record["creation_time"]) <= 0):
        invalid.append("creation_time")
    if "return_code" in record and record["return_code"] is not None and int(record["return_code"]) != 0:
        invalid.append("return_code")
    return {"pid": record.get("pid"), "missing_fields": missing, "invalid_fields": invalid, "passed": not missing and not invalid}


def audit_process_registry(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [validate_process_record(row) for row in records]
    identities = [(int(row.get("pid", -1)), float(row.get("creation_time", -1))) for row in records]
    duplicates = sorted({identity for identity in identities if identities.count(identity) > 1})
    passed = bool(rows) and not duplicates and all(row["passed"] for row in rows)
    return {"record_count": len(rows), "duplicate_pid_creation_time": [list(row) for row in duplicates],
            "records": rows, "command_cwd_complete": all("command_line" not in row["missing_fields"] and "cwd" not in row["missing_fields"] for row in rows),
            "passed": passed}


def ownership_matches(record: Mapping[str, Any], *, pid: int, creation_time: float) -> bool:
    """PID alone is insufficient because the operating system can reuse it."""
    return int(record.get("pid", -1)) == int(pid) and abs(float(record.get("creation_time", -1)) - float(creation_time)) <= 1e-6

