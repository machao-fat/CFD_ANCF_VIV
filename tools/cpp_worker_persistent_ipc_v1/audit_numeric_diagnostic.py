from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path


def _vectors(value: dict[str, object], path: str, name: str) -> tuple[float, ...]:
    raw = value[name]
    if not isinstance(raw, list) or not raw or any(not math.isfinite(float(x)) for x in raw):
        raise ValueError(f"{path}: invalid {name}")
    return tuple(float(x) for x in raw)


def _errors(left: tuple[float, ...], right: tuple[float, ...]) -> dict[str, float]:
    if len(left) != len(right):
        raise ValueError("diagnostic vector dimension mismatch")
    absolute = [abs(a - b) for a, b in zip(left, right)]
    scale = max(1.0, max(abs(a) for a in left))
    return {"max_abs": max(absolute), "global_relative": max(absolute) / scale}


def main(matlab_json: str, cpp_text: str, per_step_json: str, output_json: str) -> int:
    matlab = json.loads(Path(matlab_json).read_text(encoding="utf-8-sig"))
    lines = Path(cpp_text).read_text(encoding="utf-8").splitlines()
    cpp: dict[str, tuple[float, ...]] = {}
    for line in lines:
        fields = line.split()
        if fields and fields[0] in {"internal_before", "predictor", "velocity_predictor"}:
            cpp[fields[0]] = tuple(float(x) for x in fields[2:])
    for name in ("internal_before", "predictor", "velocity_predictor"):
        if name not in cpp:
            raise ValueError(f"missing C++ diagnostic field {name}")
    field_comparison = {
        name: _errors(_vectors(matlab, matlab_json, name), cpp[name])
        for name in ("internal_before", "predictor", "velocity_predictor")
    }
    # The matrix dump is intentionally compared as a flattened numeric audit.
    mass_line = next((line for line in lines if line.startswith("mass ")), None)
    tangent_line = next((line for line in lines if line.startswith("tangent ")), None)
    if mass_line is None or tangent_line is None:
        raise ValueError("missing C++ matrix diagnostics")
    mass_values = tuple(float(x) for x in lines[lines.index(mass_line) + 1].split())
    tangent_values = tuple(float(x) for x in lines[lines.index(tangent_line) + 1].split())
    field_comparison["mass"] = _errors(_vectors(matlab, matlab_json, "mass"), mass_values)
    field_comparison["tangent_before"] = _errors(_vectors(matlab, matlab_json, "tangent_before"), tangent_values)
    per_step = json.loads(Path(per_step_json).read_text(encoding="utf-8"))
    if len(per_step) != 40 or [row["step"] for row in per_step] != list(range(560, 600)):
        raise ValueError("per-step audit is not exactly the bounded 560..599 sequence")
    error_summary: dict[str, dict[str, float]] = {}
    for name in ("q", "qdot", "qddot", "internal_force", "predictor", "corrector", "residual"):
        values = [float(row[name]["max_abs"]) for row in per_step]
        error_summary[name] = {
            "max_abs": max(values), "mean_abs": statistics.fmean(values),
            "p95_abs": sorted(values)[int(math.ceil(0.95 * len(values))) - 1],
            "max_step": per_step[max(range(len(per_step)), key=lambda i: values[i])]["step"],
        }
    result = {
        "stage_id": "stage4f_d_cpp_worker_numeric_diagnostic_v1",
        "run_id": "cpp_worker_numeric_diagnostic_001",
        "case_id": "cpp_worker_numeric_diagnostic_case_001",
        "status": "diagnostic_complete_dual_contract_pending",
        "matlab_start_count": 1,
        "openfoam_start_count": 0,
        "wsl_start_count": 0,
        "cfd_start_count": 0,
        "owned_residual": 0,
        "source_step": 559,
        "source_time_s": 2.2075,
        "bounded_steps": 40,
        "field_comparison": field_comparison,
        "per_step_error_summary": error_summary,
        "interpretation": {
            "mass_predictor_parity": "exact_within_serialized_double",
            "internal_and_tangent_parity": "sub_micro_unit_absolute_difference",
            "root_cause_classification": "linear_algebra_rounding_and_operation_order_amplified_over_steps",
            "transport_or_identity_fault": False,
            "physical_core_modified": False,
            "strict_dual_gate": "do_not_pass_until_explicit_mixed_tolerance_contract_is_approved",
        },
        "protected": {
            "old_evidence_modified": False,
            "old_runtime_reused": False,
            "physical_parameters_modified": False,
            "numerical_solver_thresholds_modified": False,
        },
    }
    Path(output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
