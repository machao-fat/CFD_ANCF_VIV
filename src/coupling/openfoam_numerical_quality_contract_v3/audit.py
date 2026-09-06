"""Evaluate a frozen V3 OpenFOAM quality contract without changing V2 history."""
from __future__ import annotations

import math
from typing import Any, Mapping

from coupling.openfoam_numerical_quality_contract_v2.audit import AuditError, audit_log


def _number(value: object, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{label} is not numeric") from exc
    if not math.isfinite(parsed):
        raise AuditError(f"{label} is non-finite")
    return parsed


def _allowed(rule: Mapping[str, object], initial: float) -> float:
    return max(_number(rule["absolute_tolerance"], "absolute tolerance"),
               _number(rule["relative_tolerance"], "relative tolerance") * initial)


def evaluate_quality_v3(audit: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    """Classify every solve; zero-iteration zero mesh solves are explicit health."""
    records = audit.get("time_records")
    if not isinstance(records, list) or not records:
        raise AuditError("missing time records")
    groups = contract["solve_groups"]
    field_to_group = {field: group_name for group_name, rule in groups.items() for field in rule["fields"]}
    failures: list[str] = []
    classifications: list[dict[str, Any]] = []
    max_final: dict[str, float] = {}
    max_courant = 0.0
    max_continuity = 0.0
    for record in records:
        time_s = _number(record["time_s"], "time")
        courant = record.get("courant_max")
        if courant is None:
            failures.append(f"missing Courant at {time_s}")
        else:
            max_courant = max(max_courant, _number(courant, "Courant"))
        continuity = record.get("continuity")
        if not isinstance(continuity, list) or not continuity:
            failures.append(f"missing continuity at {time_s}")
        else:
            max_continuity = max(max_continuity, max(abs(_number(item["global"], "continuity")) for item in continuity))
        solved_fields = {str(solve["field"]) for solve in record["solves"]}
        for group_name, rule in groups.items():
            for expected in rule["fields"]:
                if expected not in solved_fields:
                    failures.append(f"missing {group_name} solve {expected} at {time_s}")
        for solve in record["solves"]:
            field = str(solve["field"])
            group_name = field_to_group.get(field)
            if group_name is None:
                failures.append(f"unclassified solve {field} at {time_s}")
                continue
            rule = groups[group_name]
            initial = _number(solve["initial_residual"], "initial residual")
            final = _number(solve["final_residual"], "final residual")
            iterations = int(solve["linear_iterations"])
            max_final[field] = max(max_final.get(field, 0.0), final)
            trivial = group_name == "mesh_motion_auxiliary" and initial == 0.0 and final == 0.0 and iterations == 0
            healthy = trivial or (iterations > 0 and iterations <= int(rule["max_iterations"]) and final <= _allowed(rule, initial))
            classifications.append({"time_s": time_s, "field": field, "group": group_name,
                                    "initial_residual": initial, "final_residual": final,
                                    "linear_iterations": iterations,
                                    "trivially_converged": trivial, "solver_health": "pass" if healthy else "fail"})
            if not healthy:
                failures.append(f"{group_name} solver health failure for {field} at {time_s}")
        terminal = record["metrics"]["field_terminal_final_residual"]
        for field, limit in contract["primary_terminal_residual_limit"].items():
            if field not in terminal:
                failures.append(f"missing primary terminal {field} at {time_s}")
            elif _number(terminal[field], f"terminal {field}") > _number(limit, f"terminal limit {field}"):
                failures.append(f"primary terminal {field} exceeds limit at {time_s}")
    if max_courant > _number(contract["courant_max_limit"], "Courant max limit"):
        failures.append("Courant quality failure")
    if max_continuity > _number(contract["continuity_global_abs_limit"], "continuity limit"):
        failures.append("continuity quality failure")
    return {"schema_version": "openfoam-numerical-quality-evidence-v3", "status": "pass" if not failures else "fail",
            "failures": failures, "classifications": classifications, "max_final_residual_by_field": max_final,
            "max_courant": max_courant, "max_abs_continuity_global": max_continuity,
            "observability_completeness": "pass" if not any("missing" in item or "unclassified" in item for item in failures) else "fail",
            "linear_solver_health": "pass" if not any("solver health" in item for item in failures) else "fail",
            "pimple_terminal_convergence": "pass" if not any("primary terminal" in item for item in failures) else "fail"}


def audit_and_evaluate_v3(log_path: Any, fv_solution_path: Any, contract: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    audit = audit_log(log_path, fv_solution_path)
    return audit, evaluate_quality_v3(audit, contract)
