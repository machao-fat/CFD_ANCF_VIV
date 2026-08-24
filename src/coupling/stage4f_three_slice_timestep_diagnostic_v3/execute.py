from __future__ import annotations

from typing import Any, Callable, Mapping

from ..stage4f_three_slice_timestep_diagnostic_v2.audit import audit_branch, audit_step
from ..stage4f_three_slice_timestep_diagnostic_v2.contract import BRANCHES, START_TIME_S


def execute_d2(run_one_step: Callable[[int, float], Mapping[str, Any]], shutdown_owned: Callable[[], None]) -> dict[str, Any]:
    """Run all D2 diagnostic points; Cd/velocity failures are recorded, not hidden."""
    rows = []
    error = None
    try:
        for index in range(BRANCHES["D2"]["steps"]):
            target = START_TIME_S + (index + 1) * BRANCHES["D2"]["dt_s"]
            row = dict(run_one_step(index, target)); rows.append(row)
            decision = audit_step(row, branch="D2", expected_step=index)
            blocking = set(decision["blocking_failures"])
            blocking -= {"abs_cd", "velocity_consistency"}
            if blocking:
                error = f"hard gate failed at D2 step {index}: {','.join(sorted(blocking))}"
                break
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        shutdown_owned()
    result = audit_branch("D2", rows)
    result["steps"] = rows
    result["execution_error"] = error
    result["diagnostic_continued_through_cd_velocity_failures"] = True
    return result

