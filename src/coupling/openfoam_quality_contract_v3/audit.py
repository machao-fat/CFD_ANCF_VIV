"""Quality semantics for historical audits and future frozen contracts."""
from __future__ import annotations

import math
from statistics import median
from typing import Mapping, Sequence


FIELDS = ("time_s", "courant_max", "residual_max", "continuity_global", "iterations_max")
RESIDUAL_DEFINITION = "max_final_residual_across_all_parsed_Solving_for_lines_per_time"
CONTINUITY_DEFINITION = "last_parsed_global_continuity_error_per_time"
ITERATION_DEFINITION = "maximum_iterations_across_all_parsed_Solving_for_lines_per_time"


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def validate_numerical_quality_contract(contract: Mapping[str, object]) -> dict[str, object]:
    checks = {
        "schema_version": contract.get("schema_version") == 1,
        "frozen_before_run": contract.get("frozen_before_run") is True,
        "courant_limit": finite(contract.get("courant_limit")) and float(contract["courant_limit"]) > 0.0,
        "residual_definition": contract.get("residual_definition") == RESIDUAL_DEFINITION,
        "residual_limit": finite(contract.get("residual_limit")) and 0.0 < float(contract["residual_limit"]) < 1.0,
        "continuity_definition": contract.get("continuity_definition") == CONTINUITY_DEFINITION,
        "continuity_limit": finite(contract.get("continuity_limit")) and float(contract["continuity_limit"]) >= 0.0,
        "iteration_definition": contract.get("iteration_definition") == ITERATION_DEFINITION,
        "iteration_limit_or_warning": finite(contract.get("iteration_limit")) and float(contract["iteration_limit"]) >= 1.0,
    }
    return {"checks": checks, "status": "pass" if all(checks.values()) else "fail"}


def audit_records(records: Sequence[Mapping[str, object]], *, expected_count: int, expected_start_s: float | None = None,
                  dt_s: float = 0.005, numerical_contract: Mapping[str, object] | None = None) -> dict[str, object]:
    checks = {"record_count": len(records) == expected_count, "required_fields": True, "finite_fields": True,
              "strictly_increasing_time": True, "uniform_dt": True, "expected_start": True}
    times: list[float] = []
    for record in records:
        checks["required_fields"] &= all(field in record for field in FIELDS)
        if not all(field in record for field in FIELDS):
            continue
        checks["finite_fields"] &= all(finite(record[field]) for field in FIELDS)
        if finite(record["time_s"]):
            times.append(float(record["time_s"]))
    for left, right in zip(times, times[1:]):
        checks["strictly_increasing_time"] &= right > left
    if len(times) > 1:
        deltas = [right - left for left, right in zip(times, times[1:])]
        checks["uniform_dt"] &= all(abs(delta - dt_s) <= max(1.0e-9, dt_s * 1.0e-6) for delta in deltas)
    elif expected_count > 1:
        checks["uniform_dt"] = False
    if expected_start_s is not None:
        checks["expected_start"] &= bool(times) and abs(times[0] - expected_start_s) <= 1.0e-9
    observability = {"status": "pass" if all(checks.values()) else "fail", "checks": checks,
                     "record_count": len(records), "expected_count": expected_count,
                     "field_definitions": {"courant_max": "maximum Courant Number printed for the time record", "residual_max": RESIDUAL_DEFINITION,
                                           "continuity_global": CONTINUITY_DEFINITION, "iterations_max": ITERATION_DEFINITION}}
    if numerical_contract is None:
        numerical = {"status": "not_evaluable", "reason": "no frozen pre-run numerical-quality contract retained with the historical records"}
    else:
        contract_audit = validate_numerical_quality_contract(numerical_contract)
        if contract_audit["status"] != "pass" or observability["status"] != "pass":
            numerical = {"status": "not_evaluable", "reason": "contract invalid or quality records incomplete", "contract_audit": contract_audit}
        else:
            violations = {
                "courant": sum(float(row["courant_max"]) > float(numerical_contract["courant_limit"]) for row in records),
                "residual": sum(float(row["residual_max"]) > float(numerical_contract["residual_limit"]) for row in records),
                "continuity": sum(abs(float(row["continuity_global"])) > float(numerical_contract["continuity_limit"]) for row in records),
                "iterations": sum(float(row["iterations_max"]) > float(numerical_contract["iteration_limit"]) for row in records),
            }
            numerical = {"status": "pass" if not any(violations.values()) else "fail", "contract_audit": contract_audit, "violating_record_count": violations}
    return {"OBSERVABILITY_COMPLETENESS": observability, "NUMERICAL_QUALITY": numerical}
