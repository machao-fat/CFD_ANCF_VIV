"""Run the frozen V1.3 generic static-prestress regression.

This driver deliberately keeps the existing V1.2 helper/result contract and
changes only the generic-prestress orchestration and diagnostic gate names.
It performs the semantic self-test and offline suite before the first static
evaluation, then executes low/high endpoints followed by deterministic
bisection without retries.
"""

from __future__ import annotations

from copy import deepcopy
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.precice_ancf_adapter_v1.ancf_case_config_v1 import CaseConfig, CaseConfigError
from tools.precice_ancf_adapter_v1.ancf_generic_participant_v1 import GenericANCFParticipant
from tools.precice_ancf_adapter_v1.ancf_static_prestress_v1 import (
    PrestressError,
    StaticPrestressInitializer,
    compare_calibrations,
    make_synthetic_case,
)
from tools.precice_ancf_adapter_v1.run_static_prestress_regression_v1 import (
    _invalid_case_results,
)


PROTOCOL_SHA256 = "6DA632477945D5D1DD7743185B2FB90BAFFAD18F4E423C10D5AD30B34C58AEB8"
BASELINE_COMMIT = "df34462fa483260b45beade369b0b682ff5f4765"
HISTORICAL_DELTA = 0.034885254954215579
HISTORICAL_TOP = 5000.0005178807523
TARGET = 5000.0
TARGET_TOLERANCE = 1.0e-6
GLOBAL_BALANCE_TOLERANCE = 1.0e-10
DELTA_TOLERANCE = 1.0e-8
COMPARISON_TOLERANCE = 1.0e-11
RESULT_PREFIX = "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1.3"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def _config(raw: Mapping[str, Any], output_dir: Path) -> CaseConfig:
    return CaseConfig.from_mapping(raw, base_dir=output_dir)


def _run_semantic_self_test(driver: Path, evidence_dir: Path) -> dict[str, Any]:
    command = [str(driver), "--diagnostic-semantics-self-test"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    result = {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    _write_json(evidence_dir / "diagnostic_semantics_self_test.json", result)
    return result


def _fresh_offline_suite() -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "discover", "-s",
               "tools/precice_ancf_adapter_v1/tests", "-p", "test_*.py", "-q"]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False,
        env={**dict(__import__("os").environ),
             "PYTHONPATH": f"{ROOT};{ROOT / 'src'}"},
    )
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _calibrate_in_order(initializer: StaticPrestressInitializer) -> dict[str, Any]:
    """Perform low, high, then deterministic bisection in frozen order."""
    spec = initializer.spec
    low_delta = float(spec["delta_length_low_m"])
    high_delta = float(spec["delta_length_high_m"])
    low = initializer._evaluate(low_delta, 0)
    high = initializer._evaluate(high_delta, 0)
    low_f = float(low["top_tension_N"]) - float(spec["target_reaction_N"])
    high_f = float(high["top_tension_N"]) - float(spec["target_reaction_N"])
    if low_f * high_f >= 0.0:
        raise PrestressError("TARGET_REACTION_BRACKET_FAIL")

    final: Mapping[str, Any] | None = None
    final_delta: float | None = None
    for iteration in range(1, int(spec["max_iterations"]) + 1):
        delta = 0.5 * (low_delta + high_delta)
        candidate = initializer._evaluate(delta, iteration)
        final = candidate
        final_delta = delta
        candidate_f = float(candidate["top_tension_N"]) - float(spec["target_reaction_N"])
        relative_error = abs(candidate_f) / float(spec["target_reaction_N"])
        if relative_error <= float(spec["relative_target_tolerance"]):
            break
        if low_f * candidate_f < 0.0:
            high_delta, high_f = delta, candidate_f
        else:
            low_delta, low_f = delta, candidate_f
    else:
        raise PrestressError("TARGET_REACTION_CALIBRATION_FAIL")

    assert final is not None and final_delta is not None
    return {
        "final_delta_length_m": final_delta,
        "final": final,
        "bracket_low": low,
        "bracket_high": high,
        "bracket_low_f_N": low_f,
        "bracket_high_f_N": high_f,
        "bracket_valid": True,
        "static_solves": initializer.static_solves,
        "total_newton_iterations": initializer.total_newton_iterations,
        "potential_non_descent_failures": initializer.potential_non_descent_failures,
        "potential_line_search_failures": initializer.potential_line_search_failures,
        "minimum_accepted_beta": initializer.minimum_accepted_beta,
        "maximum_backtrack_depth": initializer.maximum_backtrack_depth,
        "unchanged_trials_seen": initializer.unchanged_trials_seen,
        "unchanged_trials_accepted": initializer.unchanged_trials_accepted,
        "history": list(initializer.history),
    }


def _write_history(path: Path, history: list[Mapping[str, Any]]) -> None:
    fields = [
        "evaluation_id", "bisection_iteration", "DeltaL_m", "H_m", "lambda0",
        "epsilon0", "static_status", "static_Newton_iterations", "T_top_N",
        "f_N", "relative_target_error", "top_Rx_N", "top_Ry_N", "top_Rz_N",
        "bottom_Rx_N", "bottom_Ry_N", "bottom_Rz_N",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(history)


def _write_profile(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fields = ["s_ref_m", "current_z_m", "lambda", "epsilon", "T_ANCF_N",
              "T_ref_N", "difference_N", "normalized_error"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _fake_handoff(config: CaseConfig) -> dict[str, Any]:
    class Backend:
        vertex_count = 1

        def initialize(self) -> None:
            pass

    class Worker:
        def step(self, request: Any) -> Mapping[str, Any]:
            return {"q": request.q, "qdot": request.qdot, "qddot": request.qddot}

    participant = GenericANCFParticipant(config, [Backend()], Worker())
    state = config.initial_state()
    return {
        "status": "PASS",
        "q_match": tuple(participant.q) == tuple(state["q"]),
        "qdot_zero": all(value == 0.0 for value in participant.qdot),
        "qddot_zero": all(value == 0.0 for value in participant.qddot),
        "time_s": participant.time_s,
        "global_step": participant.global_step,
        "state_kind": "prestressed_start",
        "run_id": config.run_id,
    }


def _failure_result(output_dir: Path, failure: str, semantic: Mapping[str, Any],
                    offline: Mapping[str, Any]) -> dict[str, Any]:
    classification = failure.split(":", 1)[0]
    result = {
        "status": "FAIL",
        "primary_failure": classification,
        "failure_detail": failure,
        "protocol_sha256": PROTOCOL_SHA256,
        "production_commit": BASELINE_COMMIT,
        "historical_states_retained": {
            "generic_prestress_v1": "FAIL / STATIC_SOLVE_FAIL",
            "generic_prestress_v1_1": "STOPPED_BEFORE_PROTOCOL / V1_RAW_EVIDENCE_INSUFFICIENT",
            "generic_prestress_v1_2": "FAIL / NONFINITE_STATIC_RESULT",
            "residual_scale_diagnostic_v1": "FAIL",
            "residual_scale_diagnostic_v1_1": "FAIL",
            "residual_scale_diagnostic_v1_2": "PASS",
        },
        "helper_semantic_tests": dict(semantic),
        "offline_tests": dict(offline),
        "low_endpoint": {"status": "NOT_REACHED"},
        "high_endpoint": {"status": "NOT_REACHED"},
        "bracket": {"status": "NOT_REACHED"},
        "bisection_iterations": 0,
        "static_solve_count": 0,
        "final": {"status": "NOT_REACHED"},
        "explicit_section_equivalence": "NOT_RUN",
        "caller_model_static_equivalence": "NOT_RUN",
        "static_state_artifact": "NOT_GENERATED",
        "generic_participant_prestressed_start_handoff": "NOT_RUN",
        "forbidden_execution": {
            "production_modified": False, "worker_dynamic_run": False,
            "G1": False, "formal_C_F": False, "preCICE": False,
            "OpenFOAM": False, "CFD_FSI": False, "literature_case": False,
        },
    }
    _write_json(output_dir / f"{RESULT_PREFIX}_PATCH_RESULT.json", result)
    (output_dir / f"{RESULT_PREFIX}_PATCH_REPORT.md").write_text(
        f"# {RESULT_PREFIX} — Report\n\nStatus: `FAIL`\n\n"
        f"Primary frozen failure: `{classification}`\n\n{failure}\n\n"
        "No retry was performed and no later gate was run. Historical evidence "
        "remains immutable; no forbidden execution occurred.\n", encoding="utf-8")
    (output_dir / f"{RESULT_PREFIX}_TEST_RAW.txt").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def run_v13(output_dir: Path, driver: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = output_dir / f"{RESULT_PREFIX}_EVIDENCE"
    evidence.mkdir(parents=True, exist_ok=True)

    semantic = _run_semantic_self_test(driver, evidence)
    offline = _fresh_offline_suite()
    _write_json(evidence / "offline_suite.json", offline)
    if semantic["status"] != "PASS":
        return _failure_result(output_dir, "HELPER_DIAGNOSTIC_SEMANTICS_FAIL", semantic, offline)
    if offline["status"] != "PASS":
        return _failure_result(output_dir, "OFFLINE_TEST_FAIL", semantic, offline)

    state_name = f"{RESULT_PREFIX}_STATIC_STATE.json"
    legacy_raw = make_synthetic_case(state_file=state_name)
    legacy_config = _config(legacy_raw, output_dir)
    legacy_initializer = StaticPrestressInitializer(
        legacy_config, driver, result_directory=evidence / "legacy")
    try:
        legacy_calibration = _calibrate_in_order(legacy_initializer)
    except PrestressError as exc:
        return _failure_result(output_dir, str(exc), semantic, offline)

    legacy_final = legacy_calibration["final"]
    low = legacy_calibration["bracket_low"]
    high = legacy_calibration["bracket_high"]
    legacy_profile = legacy_initializer.tension_profile(legacy_final)
    _write_history(output_dir / f"{RESULT_PREFIX}_HISTORY.csv", legacy_calibration["history"])
    _write_profile(output_dir / f"{RESULT_PREFIX}_PROFILE.csv", legacy_profile)

    artifact = legacy_initializer.make_static_artifact(
        legacy_calibration, PROTOCOL_SHA256, BASELINE_COMMIT)
    artifact_path = output_dir / f"{RESULT_PREFIX}_STATIC_STATE.json"
    _write_json(artifact_path, artifact)
    try:
        artifact_state = legacy_config.initial_state()
        handoff = _fake_handoff(legacy_config)
    except (CaseConfigError, PrestressError, KeyError, TypeError, ValueError) as exc:
        return _failure_result(output_dir, f"STATIC_ARTIFACT_IDENTITY_FAIL: {exc}", semantic, offline)

    explicit_raw = deepcopy(legacy_raw)
    explicit_raw["section"]["mode"] = "explicit"
    explicit_config = _config(explicit_raw, output_dir)
    explicit_initializer = StaticPrestressInitializer(
        explicit_config, driver, result_directory=evidence / "explicit")
    explicit_calibration = _calibrate_in_order(explicit_initializer)

    caller_raw = deepcopy(legacy_raw)
    caller_raw["base_load"] = {
        "source": "caller_supplied",
        "vector": list(low["base_load"]),
    }
    caller_config = _config(caller_raw, output_dir)
    caller_initializer = StaticPrestressInitializer(
        caller_config, driver, result_directory=evidence / "caller")
    caller_calibration = _calibrate_in_order(caller_initializer)

    explicit_comparison = compare_calibrations(legacy_calibration, explicit_calibration)
    caller_comparison = compare_calibrations(legacy_calibration, caller_calibration)
    explicit_pass = all(value <= COMPARISON_TOLERANCE for value in explicit_comparison.values())
    caller_pass = all(value <= COMPARISON_TOLERANCE for value in caller_comparison.values())
    target_error = abs(float(legacy_final["top_tension_N"]) - TARGET) / TARGET
    delta_agreement = abs(float(legacy_calibration["final_delta_length_m"]) - HISTORICAL_DELTA)
    profile_error = max((row["normalized_error"] for row in legacy_profile), default=math.inf)
    profile_monotonic = all(
        legacy_profile[index]["T_ANCF_N"] <= legacy_profile[index + 1]["T_ANCF_N"] +
        1.0e-10 * max(1.0, abs(legacy_profile[index]["T_ANCF_N"]),
                       abs(legacy_profile[index + 1]["T_ANCF_N"]))
        for index in range(len(legacy_profile) - 1))
    invalid_results = _invalid_case_results(legacy_raw, output_dir)
    invalid_pass = all(item["status"] == "REJECT" for item in invalid_results)
    gates = {
        "low_status": low.get("status") == "PASS",
        "high_status": high.get("status") == "PASS",
        "bracket_sign_change": legacy_calibration["bracket_low_f_N"] * legacy_calibration["bracket_high_f_N"] < 0.0,
        "target_error": target_error <= TARGET_TOLERANCE,
        "global_balance": float(legacy_final["global_balance_error"]) <= GLOBAL_BALANCE_TOLERANCE,
        "delta_agreement": delta_agreement <= DELTA_TOLERANCE,
        "finite": all(math.isfinite(float(legacy_final[key])) for key in
                       ("top_tension_N", "global_balance_error", "residual", "residual_scale",
                        "normalized_residual")),
        "non_descent_zero": legacy_calibration["potential_non_descent_failures"] == 0,
        "line_search_zero": legacy_calibration["potential_line_search_failures"] == 0,
        "unchanged_accepted_zero": legacy_calibration["unchanged_trials_accepted"] == 0,
        "explicit_equivalence": explicit_pass,
        "caller_equivalence": caller_pass,
        "artifact_state": tuple(artifact_state["q"]) == tuple(artifact["q"]),
        "handoff": handoff["status"] == "PASS" and handoff["q_match"] and handoff["qdot_zero"] and handoff["qddot_zero"],
        "invalid_inputs": invalid_pass,
        "profile": profile_error <= 1.0e-4 and profile_monotonic,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    result = {
        "status": status,
        "primary_failure": None if status == "PASS" else "FROZEN_GATE_FAILURE",
        "protocol_sha256": PROTOCOL_SHA256,
        "production_commit": BASELINE_COMMIT,
        "historical_states_retained": {
            "generic_prestress_v1": "FAIL / STATIC_SOLVE_FAIL",
            "generic_prestress_v1_1": "STOPPED_BEFORE_PROTOCOL / V1_RAW_EVIDENCE_INSUFFICIENT",
            "generic_prestress_v1_2": "FAIL / NONFINITE_STATIC_RESULT",
            "residual_scale_diagnostic_v1": "FAIL",
            "residual_scale_diagnostic_v1_1": "FAIL",
            "residual_scale_diagnostic_v1_2": "PASS",
        },
        "helper_semantic_tests": semantic,
        "offline_tests": offline,
        "low_endpoint": low,
        "high_endpoint": high,
        "bracket": {
            "low_DeltaL_m": legacy_calibration["history"][0]["DeltaL_m"],
            "high_DeltaL_m": legacy_calibration["history"][1]["DeltaL_m"],
            "low_f_N": legacy_calibration["bracket_low_f_N"],
            "high_f_N": legacy_calibration["bracket_high_f_N"],
            "sign_change": legacy_calibration["bracket_low_f_N"] * legacy_calibration["bracket_high_f_N"] < 0.0,
        },
        "bisection_iterations": max(row["bisection_iteration"] for row in legacy_calibration["history"]),
        "static_solve_count": legacy_calibration["static_solves"],
        "final_DeltaL_m": legacy_calibration["final_delta_length_m"],
        "final_H_m": legacy_final["H_m"],
        "final_T_top_N": legacy_final["top_tension_N"],
        "target_relative_error": target_error,
        "historical_DeltaL_m": HISTORICAL_DELTA,
        "historical_T_top_N": HISTORICAL_TOP,
        "DeltaL_agreement_abs_m": delta_agreement,
        "top_reaction": legacy_final["top_reaction"],
        "bottom_reaction": legacy_final["bottom_reaction"],
        "external_total": legacy_final["external_total"],
        "global_balance_error": legacy_final["global_balance_error"],
        "potential_diagnostics": {
            "total_static_solves": legacy_calibration["static_solves"],
            "total_newton_iterations": legacy_calibration["total_newton_iterations"],
            "non_descent_failures": legacy_calibration["potential_non_descent_failures"],
            "line_search_failures": legacy_calibration["potential_line_search_failures"],
            "minimum_accepted_beta": legacy_calibration["minimum_accepted_beta"],
            "maximum_backtrack_depth": legacy_calibration["maximum_backtrack_depth"],
            "unchanged_trials_seen": legacy_calibration["unchanged_trials_seen"],
            "unchanged_trials_accepted": legacy_calibration["unchanged_trials_accepted"],
            "final_residual": legacy_final["residual"],
            "final_residual_scale": legacy_final["residual_scale"],
            "final_normalized_residual": legacy_final["normalized_residual"],
        },
        "tension_profile": {
            "sample_count": len(legacy_profile),
            "max_normalized_error": profile_error,
            "monotonic_bottom_to_top": profile_monotonic,
        },
        "legacy_explicit_equivalence": {"status": "PASS" if explicit_pass else "FAIL",
                                         "comparison": explicit_comparison},
        "model_static_caller_supplied_equivalence": {"status": "PASS" if caller_pass else "FAIL",
                                                      "comparison": caller_comparison},
        "static_state_artifact": {
            "status": "PASS" if gates["artifact_state"] else "FAIL",
            "path": str(artifact_path),
            "state_kind": artifact["state_kind"],
            "case_config_sha256": artifact["case_config_sha256"],
            "model_identity_sha256": artifact["model_identity_sha256"],
        },
        "generic_participant_prestressed_start_handoff": handoff,
        "invalid_input_tests": {
            "total": len(invalid_results),
            "passed": sum(item["status"] == "REJECT" for item in invalid_results),
            "status": "PASS" if invalid_pass else "FAIL",
            "cases": invalid_results,
        },
        "gates": gates,
        "forbidden_execution": {
            "production_modified": False, "worker_dynamic_run": False,
            "G1": False, "formal_C_F": False, "preCICE": False,
            "OpenFOAM": False, "CFD_FSI": False, "literature_case": False,
        },
        "historical_state_preserved": True,
        "independent_ANCF_validation": "NOT_COMPLETED",
    }
    _write_json(output_dir / f"{RESULT_PREFIX}_PATCH_RESULT.json", result)
    raw = "ANCF V1.3 generic static-prestress regression\n" + json.dumps(
        result, indent=2, sort_keys=True) + "\n\nCalibration history:\n"
    raw += "\n".join(json.dumps(row, sort_keys=True) for row in legacy_calibration["history"]) + "\n"
    (output_dir / f"{RESULT_PREFIX}_TEST_RAW.txt").write_text(raw, encoding="utf-8")
    report = f"""# {RESULT_PREFIX} — Report

Final status: `{status}`

- Protocol SHA-256: `{PROTOCOL_SHA256}`
- Production baseline: `{BASELINE_COMMIT}`
- Strategy: `installed_stretch_target_top_reaction`
- Low/high bracket: `{legacy_calibration['history'][0]['DeltaL_m']:.17g}` m / `{legacy_calibration['history'][1]['DeltaL_m']:.17g}` m
- Bracket residuals: `{legacy_calibration['bracket_low_f_N']:.17g}` N / `{legacy_calibration['bracket_high_f_N']:.17g}` N
- Static solves: `{legacy_calibration['static_solves']}`; bisection iterations: `{max(row['bisection_iteration'] for row in legacy_calibration['history'])}`
- Final DeltaL/H: `{legacy_calibration['final_delta_length_m']:.17g}` m / `{legacy_final['H_m']:.17g}` m
- Final top reaction: `{legacy_final['top_tension_N']:.17g}` N; relative error `{target_error:.17g}`
- Global balance error: `{legacy_final['global_balance_error']:.17g}`
- Non-descent/line-search failures: `{legacy_calibration['potential_non_descent_failures']}` / `{legacy_calibration['potential_line_search_failures']}`
- Legacy/explicit equivalence: `{explicit_pass}`; model-static/caller-supplied equivalence: `{caller_pass}`
- Static artifact and prestressed-start handoff: `{gates['artifact_state']}` / `{gates['handoff']}`
- Offline tests: `{offline['status']}`; helper semantic tests: `{semantic['status']}`

No production source was modified and no worker dynamic, G1, formal C/F,
preCICE, OpenFOAM, CFD/FSI, literature, or named-paper execution occurred.
Historical V1/V1.1/V1.2 failures remain unchanged.
"""
    (output_dir / f"{RESULT_PREFIX}_PATCH_REPORT.md").write_text(report, encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_static_prestress_regression_v1_3.py <driver.exe> <output-dir>")
    driver = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()
    try:
        result = run_v13(output_dir, driver)
    except (PrestressError, CaseConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        result = _failure_result(
            output_dir, str(exc),
            {"status": "NOT_COMPLETED"}, {"status": "NOT_COMPLETED"})
    print(json.dumps({
        "status": result["status"],
        "primary_failure": result.get("primary_failure"),
        "final_DeltaL_m": result.get("final_DeltaL_m"),
    }, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
