"""Offline assembly support. Real solvers remain owned by the main agent."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .audit import audit_branch, audit_step
from .contract import BRANCHES, END_TIME_S, START_TIME_S


def branch_plan(branch: str, root: Path, parent_checkpoint: Path) -> dict[str, Any]:
    row = BRANCHES[branch]
    root = root.resolve()
    parent_checkpoint = parent_checkpoint.resolve()
    return {"branch": branch, "dt_s": row["dt_s"], "steps": row["steps"], "start_time_s": START_TIME_S,
            "end_time_s": END_TIME_S, "slice_ids": [0, 1, 2],
            "case_root": str(root / f"branch_{branch}"), "source_checkpoint": str(parent_checkpoint),
            "diagnostic_mode": True, "continue_only_for": ["abs_cd", "velocity_consistency"] if branch == "D1" else []}


def process_record_complete(record: Mapping[str, Any]) -> bool:
    required = ("pid", "creation_time", "parent_pid", "executable", "command_line", "cwd", "start_timestamp",
                "end_timestamp", "return_code", "log_path", "shutdown_method", "ownership_basis")
    return all(key in record and record[key] not in (None, "", []) for key in required)


def execute_diagnostic(branch: str, run_one_step: Callable[[int, float], Mapping[str, Any]],
                       shutdown_owned: Callable[[], None]) -> dict[str, Any]:
    """Run one branch serially; the caller exclusively owns solver callbacks."""
    schedule = BRANCHES[branch]
    rows = []
    error = None
    try:
        for index in range(schedule["steps"]):
            target = START_TIME_S + (index + 1) * schedule["dt_s"]
            row = dict(run_one_step(index, target))
            rows.append(row)
            decision = audit_step(row, branch=branch, expected_step=index)
            if decision["blocking_failures"]:
                error = f"hard gate failed at {branch} step {index}: {','.join(decision['blocking_failures'])}"
                break
            if branch != "D1" and decision["failures"]:
                error = f"frozen hard gate failed at {branch} step {index}: {','.join(decision['failures'])}"
                break
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        shutdown_owned()
    result = audit_branch(branch, rows)
    result["steps"] = rows
    result["execution_error"] = error
    return result
