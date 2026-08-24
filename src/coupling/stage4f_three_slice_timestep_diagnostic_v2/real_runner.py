"""Real-run lifecycle helpers without changing the production coupling core."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .contract import BRANCHES, build_contract, validate_contract
from .execute import branch_plan, process_record_complete


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def freeze(*, output: Path, parent_checkpoint: Path, parent_protection_sha256: str) -> dict[str, Any]:
    value = build_contract(str(parent_checkpoint), sha256_file(parent_checkpoint), parent_protection_sha256)
    validate_contract(value); atomic_write_json(output, value); return value


def preflight(*, contract_path: Path, branch: str, case_root: Path, runtime_root: Path,
              results_root: Path, parent_checkpoint: Path) -> dict[str, Any]:
    contract_path = contract_path.resolve(); case_root = case_root.resolve(); runtime_root = runtime_root.resolve()
    results_root = results_root.resolve(); parent_checkpoint = parent_checkpoint.resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8")); validate_contract(contract)
    errors = []
    if branch not in BRANCHES: errors.append("unknown_branch")
    if not parent_checkpoint.is_file() or sha256_file(parent_checkpoint) != contract["parent_checkpoint_sha256"]: errors.append("parent_checkpoint_identity")
    roots = (case_root, runtime_root, results_root)
    if len({str(path.resolve()).lower() for path in roots}) != 3: errors.append("roots_not_isolated")
    for path in roots:
        if "stage4f_three_slice_timestep_diagnostic_v2" not in str(path): errors.append(f"non_v2_root:{path}")
    value = {"status": "passed" if not errors else "blocked", "branch": branch, "errors": errors,
             "plan": branch_plan(branch, case_root, parent_checkpoint) if branch in BRANCHES else None,
             "checked_at": utc_now()}
    return value


def normalize_process_record(record: Mapping[str, Any]) -> dict[str, Any]:
    command = record.get("command_line_observed") or record.get("command_line")
    value = {"pid": record.get("pid"), "creation_time": record.get("creation_time"),
             "parent_pid": record.get("parent_pid_observed", record.get("parent_pid")),
             "executable": record.get("executable"), "command_line": command, "cwd": record.get("cwd"),
             "start_timestamp": record.get("creation_time_utc", record.get("start_timestamp")),
             "end_timestamp": record.get("end_timestamp"), "return_code": record.get("return_code"),
             "log_path": record.get("log_path", record.get("log")), "shutdown_method": record.get("shutdown_method", record.get("close_method")),
             "ownership_basis": record.get("ownership_basis", "Popen PID plus observed creation time and parent PID")}
    value["evidence_complete"] = process_record_complete(value)
    return value


def process_closeout(records: Sequence[Mapping[str, Any]], *, residual_identities: Sequence[Sequence[Any]]) -> dict[str, Any]:
    normalized = [normalize_process_record(row) for row in records]
    complete = bool(normalized) and all(row["evidence_complete"] for row in normalized)
    closed = sum(row["end_timestamp"] not in (None, "") and row["return_code"] is not None for row in normalized)
    return {"started": len(normalized), "closed": closed, "residual": len(residual_identities),
            "command_cwd_complete": all(row["command_line"] not in (None, "", []) and row["cwd"] not in (None, "") for row in normalized),
            "records": normalized, "residual_identities": [list(row) for row in residual_identities],
            "passed": complete and closed == len(normalized) and not residual_identities}


def stamp_process_end(record: dict[str, Any], *, return_code: int, shutdown_method: str) -> None:
    record.update({"end_timestamp": utc_now(), "return_code": int(return_code), "shutdown_method": shutdown_method})
