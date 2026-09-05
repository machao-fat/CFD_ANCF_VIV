"""Read-only parser for raw OpenFOAM stdout used by quality-contract V2."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Mapping


class AuditError(ValueError):
    pass


# Foundation OpenFOAM writes either ``Time = 0.05`` or ``Time = 0.05s``
# depending on the configured user-time unit.  Allow harmless whitespace
# before the optional unit, but keep the expression anchored so solver lines
# cannot be misclassified as time records.
_TIME = re.compile(r"^Time\s*=\s*([0-9.+\-eE]+)\s*(?:s)?\s*$")
_COURANT = re.compile(r"^Courant Number mean:\s*([^\s]+)\s+max:\s*([^\s]+)\s*$")
_SOLVE = re.compile(
    r"^[^:]+:\s+Solving for ([^,]+), Initial residual = ([^,]+), "
    r"Final residual = ([^,]+), No Iterations (\d+)\s*$"
)
_CONTINUITY = re.compile(
    r"^time step continuity errors\s*:\s*sum local = ([^,]+), global = ([^,]+), cumulative = ([^\s]+)\s*$"
)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _finite(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise AuditError(f"{name} is non-finite")
    return result


def _block(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*\{{", text)
    if match is None:
        raise AuditError(f"fvSolution block {name} is missing")
    start = text.find("{", match.start())
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    raise AuditError(f"fvSolution block {name} is unclosed")


def _entry(block: str, name: str) -> str | None:
    match = re.search(rf"(?:^|[\n{{])\s*{re.escape(name)}\s+([^;]+);", block)
    return match.group(1).strip() if match else None


def _solver_entry(block: str, parent: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {}
    inherit = _entry(block, "$")
    # `$p;` is represented as a value in the first token, not an assignment.
    inherited_name = None
    inherited_match = re.search(r"(?m)^\s*\$(\w+)\s*;", block)
    if inherited_match:
        inherited_name = inherited_match.group(1)
    if parent is not None:
        value.update(parent)
    if inherited_name is not None:
        value["inherits"] = inherited_name
    for key in ("solver", "smoother", "preconditioner", "tolerance", "relTol"):
        raw = _entry(block, key)
        if raw is not None:
            value[key] = _finite(raw, key) if key in {"tolerance", "relTol"} else raw
    if "solver" not in value or "tolerance" not in value or "relTol" not in value:
        raise AuditError("fvSolution solver entry is incomplete")
    return value


def parse_fv_solution(path: Path) -> dict[str, Any]:
    """Extract only fields required by V2 from a concrete `fvSolution` file."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    solvers = _block(text, "solvers")
    p = _solver_entry(_block(solvers, "p"))
    u = _solver_entry(_block(solvers, "U"))
    result = {
        "source_path": str(path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "solvers": {
            "p": p,
            "pFinal": _solver_entry(_block(solvers, "pFinal"), p),
            "pcorr": _solver_entry(_block(solvers, "pcorr")),
            "pcorrFinal": _solver_entry(_block(solvers, "pcorrFinal"), _solver_entry(_block(solvers, "pcorr"))),
            "U": u,
            "UFinal": _solver_entry(_block(solvers, "UFinal"), u),
            "cellMotionUx": _solver_entry(_block(solvers, "cellMotionUx")),
        },
    }
    pimple = _block(text, "PIMPLE")
    for key in ("nOuterCorrectors", "nCorrectors", "nNonOrthogonalCorrectors"):
        raw_value = _entry(pimple, key)
        if raw_value is None or not raw_value.isdigit():
            raise AuditError(f"PIMPLE {key} is missing or invalid")
        result.setdefault("PIMPLE", {})[key] = int(raw_value)
    for key in ("correctPhi", "correctMeshPhi"):
        raw_value = _entry(pimple, key)
        result["PIMPLE"][key] = raw_value
    result["PIMPLE"]["residualControl_present"] = bool(re.search(r"(?m)^\s*residualControl\s*\{", pimple))
    return result


def _record(time_s: float, *, courant_max: float | None, pimple: Mapping[str, Any]) -> dict[str, Any]:
    return {"time_s": time_s, "courant_max": courant_max, "solves": [], "continuity": [],
            "outer_corrector": 1 if pimple["nOuterCorrectors"] == 1 else "unknown",
            "pressure_corrector": "unknown",
            "non_orthogonal_corrector": 0 if pimple["nNonOrthogonalCorrectors"] == 0 else "unknown"}


def audit_log(log_path: Path, fv_solution_path: Path) -> dict[str, Any]:
    """Parse raw stdout without modifying it and derive terminal field metrics."""
    cfg = parse_fv_solution(fv_solution_path)
    raw = log_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditError("raw OpenFOAM stdout is not UTF-8") from exc
    records: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    pending_courant: float | None = None
    for raw_line in text.splitlines():
        line = _ANSI.sub("", raw_line).strip()
        courant = _COURANT.match(line)
        if courant:
            pending_courant = _finite(courant.group(2), "Courant max")
            continue
        moment = _TIME.match(line)
        if moment:
            active = _record(_finite(moment.group(1), "time"), courant_max=pending_courant, pimple=cfg["PIMPLE"])
            records.append(active)
            pending_courant = None
            continue
        if active is None:
            continue
        solve = _SOLVE.match(line)
        if solve:
            field = solve.group(1).strip()
            active["solves"].append({"field": field, "initial_residual": _finite(solve.group(2), "initial residual"),
                "final_residual": _finite(solve.group(3), "final residual"), "linear_iterations": int(solve.group(4)),
                "solve_index": len(active["solves"]) + 1,
                "outer_corrector": active["outer_corrector"], "pressure_corrector": "unknown",
                "non_orthogonal_corrector": active["non_orthogonal_corrector"]})
            continue
        continuity = _CONTINUITY.match(line)
        if continuity:
            active["continuity"].append({"local": _finite(continuity.group(1), "continuity local"),
                "global": _finite(continuity.group(2), "continuity global"),
                "cumulative": _finite(continuity.group(3), "continuity cumulative")})
    if not records:
        raise AuditError("no OpenFOAM time records were parsed")
    previous = -math.inf
    for record in records:
        if record["time_s"] <= previous:
            raise AuditError("time records are not strictly increasing")
        previous = record["time_s"]
        if not record["solves"]:
            raise AuditError(f"time {record['time_s']} has no solver lines")
        by_field: dict[str, list[dict[str, Any]]] = {}
        for solve in record["solves"]:
            by_field.setdefault(str(solve["field"]), []).append(solve)
        for rows in by_field.values():
            for row in rows:
                row["terminal_for_field"] = row is rows[-1]
                row["reduction_ratio"] = row["final_residual"] / row["initial_residual"] if row["initial_residual"] else None
        record["metrics"] = {
            "legacy_max_final_residual": max(row["final_residual"] for row in record["solves"]),
            "field_max_final_residual": {field: max(row["final_residual"] for row in rows) for field, rows in by_field.items()},
            "field_terminal_final_residual": {field: rows[-1]["final_residual"] for field, rows in by_field.items()},
            "field_terminal_reduction_ratio": {field: rows[-1]["reduction_ratio"] for field, rows in by_field.items()},
        }
    return {"schema_version": "openfoam-numerical-quality-evidence-v2", "parser_version": "1.0.1",
            "source_log": str(log_path), "source_log_sha256": hashlib.sha256(raw).hexdigest(),
            "fvSolution": cfg, "time_records": records}


def evaluate_quality(audit: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate V2 fixed gates; legacy residual remains a diagnostic only."""
    records = audit.get("time_records")
    if not isinstance(records, list) or not records:
        raise AuditError("quality audit has no time records")
    required = contract["pimple_terminal_convergence"]["required_fields"]
    terminal_limits = contract["pimple_terminal_convergence"]["per_field_absolute_final_residual_limit"]
    courant_limit = _finite(contract["courant_quality"]["max_limit"], "Courant limit")
    continuity_limit = _finite(contract["continuity_quality"]["global_abs_limit"], "continuity limit")
    iteration_limit = int(contract["iteration_health"]["linear_iterations_max"])
    linear = contract["linear_solver_health"]["per_field_base_solver"]
    failures: list[str] = []
    max_terminal = {field: 0.0 for field in required}
    max_courant = 0.0; max_continuity = 0.0; max_iterations = 0
    linear_failures: list[str] = []
    for row in records:
        if row.get("courant_max") is None:
            failures.append(f"missing Courant at time {row.get('time_s')}")
        else:
            max_courant = max(max_courant, float(row["courant_max"]))
        continuity = row.get("continuity")
        if not isinstance(continuity, list) or not continuity:
            failures.append(f"missing continuity at time {row.get('time_s')}")
        else:
            max_continuity = max(max_continuity, max(abs(float(v["global"])) for v in continuity))
        terminal = row["metrics"]["field_terminal_final_residual"]
        for field in required:
            if field not in terminal:
                failures.append(f"missing terminal {field} at time {row.get('time_s')}")
                continue
            value = float(terminal[field]); max_terminal[field] = max(max_terminal[field], value)
            if value > _finite(terminal_limits[field], f"terminal limit {field}"):
                failures.append(f"terminal {field} exceeds limit at time {row.get('time_s')}")
        for solve in row["solves"]:
            iterations = int(solve["linear_iterations"]); max_iterations = max(max_iterations, iterations)
            if iterations <= 0 or iterations > iteration_limit:
                failures.append(f"linear iteration health failure at time {row.get('time_s')}")
            field = str(solve["field"])
            base = "p" if field == "p" else "U" if field in {"Ux", "Uy", "Uz"} else None
            if base is None:
                linear_failures.append(f"uncontracted solved field {field} at time {row.get('time_s')}")
                continue
            rule = linear.get(base)
            if not isinstance(rule, Mapping):
                linear_failures.append(f"missing linear contract for {base}")
                continue
            allowed = max(_finite(rule["absolute_tolerance"], f"{base} tolerance"),
                          _finite(rule["relative_tolerance"], f"{base} relTol") * float(solve["initial_residual"]))
            if float(solve["final_residual"]) > allowed:
                linear_failures.append(f"linear solve {field} exceeds tolerance envelope at time {row.get('time_s')}")
    if max_courant > courant_limit:
        failures.append("Courant quality failure")
    if max_continuity > continuity_limit:
        failures.append("continuity quality failure")
    failures.extend(linear_failures)
    legacy = max(float(row["metrics"]["legacy_max_final_residual"]) for row in records)
    return {"status": "pass" if not failures else "fail", "failures": failures,
            "observability_completeness": "pass" if not any("missing" in v or "uncontracted" in v for v in failures) else "fail",
            "linear_solver_health": "pass" if not linear_failures else "fail",
            "pimple_terminal_convergence": "pass" if not any("terminal" in v for v in failures) else "fail",
            "courant_quality": "pass" if max_courant <= courant_limit else "fail",
            "continuity_quality": "pass" if max_continuity <= continuity_limit else "fail",
            "iteration_health": "pass" if max_iterations <= iteration_limit else "fail",
            "legacy_max_final_residual_diagnostic": legacy,
            "max_terminal_final_residual": max_terminal, "max_courant": max_courant,
            "max_abs_continuity_global": max_continuity, "max_linear_iterations": max_iterations}
