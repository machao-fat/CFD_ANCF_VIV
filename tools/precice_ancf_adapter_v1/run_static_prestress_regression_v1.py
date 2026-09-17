"""Run the frozen generic static-prestress synthetic regression."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
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
    RESULT_SCHEMA_VERSION,
    StaticPrestressInitializer,
    compare_calibrations,
    make_synthetic_case,
    read_result_file,
)


PROTOCOL_SHA256 = "DE1A438E70717DE4C0297754AB6F37E73AC1F228B956C87F870C46DB38C2A385"
BASELINE_COMMIT = "d9ed89e948c3dc87a5588f33f432b4ba5a323f8c"
HISTORICAL_DELTA = 0.034885254954215579
HISTORICAL_TOP = 5000.0005178807523
COMPARISON_TOLERANCE = 1.0e-11


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def _config(raw: Mapping[str, Any], output_dir: Path) -> CaseConfig:
    return CaseConfig.from_mapping(raw, base_dir=output_dir)


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
        "resolved_fixed_dof": list(participant.model.fixed_dof),
        "resolved_prescribed_values": list(participant.model.prescribed_values),
        "state_kind": "prestressed_start",
    }


def _invalid_case_results(base_raw: Mapping[str, Any], output_dir: Path) -> list[dict[str, str]]:
    cases: list[tuple[str, Any]] = []

    def add(name: str, mutate: Any) -> None:
        raw = deepcopy(dict(base_raw))
        mutate(raw)
        cases.append((name, raw))

    add("unknown_prestress_mode", lambda raw: raw["prestress"].update(mode="unknown"))
    add("nonpositive_target", lambda raw: raw["prestress"].update(target_reaction_N=0.0))
    add("zero_installation_axis", lambda raw: raw["prestress"].update(installation_axis=[0.0, 0.0, 0.0]))
    add("invalid_bracket_order", lambda raw: raw["prestress"].update(
        delta_length_low_m=0.1, delta_length_high_m=0.1))
    add("incompatible_boundary", lambda raw: raw.update(boundary={
        "contract_id": "invalid_gradient_constraint",
        "fixed_dof": [0, 1, 2, 6 * raw["model"]["elements"],
                      6 * raw["model"]["elements"] + 1,
                      6 * raw["model"]["elements"] + 2,
                      6 * raw["model"]["elements"] + 5],
        "prescribed_values": [0.0] * 7,
    }))
    results = []
    for name, raw in cases:
        try:
            config = _config(raw, output_dir)
            config.prestress_spec()
        except (CaseConfigError, PrestressError, KeyError, TypeError, ValueError) as exc:
            results.append({"name": name, "status": "REJECT", "reason": str(exc)})
        else:
            results.append({"name": name, "status": "ACCEPT_UNEXPECTEDLY", "reason": ""})

    # A no-sign-change bracket is a deterministic pre-calibration contract
    # check. This uses a fake, non-physical runner and does not execute ANCF.
    def fake_runner(_: str) -> Mapping[str, Any]:
        return {
            "status": "PASS", "top_tension_N": 5000.0,
            "top_reaction": [0.0, 0.0, 5000.0],
            "bottom_reaction": [0.0, 0.0, -5000.0],
            "iterations": 1, "non_descent_failures": 0,
            "line_search_failures": 0, "minimum_accepted_beta": 1.0,
            "maximum_backtrack_depth": 0, "unchanged_trials_seen": 0,
            "unchanged_trials_accepted": 0, "base_load": [0.0] * 102,
            "q": [0.0] * 102, "qdot": [0.0] * 102, "qddot": [0.0] * 102,
            "global_balance_error": 0.0, "max_abs_lambda_minus_1": 0.0,
        }

    try:
        config = _config(base_raw, output_dir)
        StaticPrestressInitializer(config, "unused", runner=fake_runner).calibrate()
    except PrestressError as exc:
        results.append({"name": "bracket_without_sign_change", "status": "REJECT", "reason": str(exc)})
    else:
        results.append({"name": "bracket_without_sign_change",
                        "status": "ACCEPT_UNEXPECTEDLY", "reason": ""})
    return results


def run(output_dir: Path, driver: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    state_name = "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_STATIC_STATE.json"
    legacy_raw = make_synthetic_case(state_file=state_name)
    legacy_config = _config(legacy_raw, output_dir)
    legacy_initializer = StaticPrestressInitializer(legacy_config, driver)
    legacy_calibration = legacy_initializer.calibrate()
    legacy_final = legacy_calibration["final"]
    legacy_profile = legacy_initializer.tension_profile(legacy_final)
    legacy_initializer.write_history(
        output_dir / "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_HISTORY.csv")
    with (output_dir / "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_PROFILE.csv").open(
            "w", encoding="utf-8", newline="") as handle:
        import csv
        fields = ["s_ref_m", "current_z_m", "lambda", "epsilon",
                  "T_ANCF_N", "T_ref_N", "difference_N", "normalized_error"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(legacy_profile)

    artifact = legacy_initializer.make_static_artifact(
        legacy_calibration, PROTOCOL_SHA256, BASELINE_COMMIT)
    artifact_path = output_dir / state_name
    _write_json(artifact_path, artifact)
    handoff = _fake_handoff(legacy_config)
    artifact_validation = legacy_config.initial_state()
    if tuple(artifact_validation["q"]) != tuple(artifact["q"]):
        raise PrestressError("STATIC_ARTIFACT_IDENTITY_FAIL")

    explicit_raw = deepcopy(legacy_raw)
    explicit_raw["section"]["mode"] = "explicit"
    explicit_config = _config(explicit_raw, output_dir)
    explicit_initializer = StaticPrestressInitializer(explicit_config, driver)
    explicit_calibration = explicit_initializer.calibrate()

    caller_raw = deepcopy(legacy_raw)
    caller_raw["base_load"] = {
        "source": "caller_supplied",
        "vector": list(legacy_calibration["bracket_low"]["base_load"]),
    }
    caller_config = _config(caller_raw, output_dir)
    caller_initializer = StaticPrestressInitializer(caller_config, driver)
    caller_calibration = caller_initializer.calibrate()

    explicit_comparison = compare_calibrations(legacy_calibration, explicit_calibration)
    caller_comparison = compare_calibrations(legacy_calibration, caller_calibration)
    target_error = abs(float(legacy_final["top_tension_N"]) - 5000.0) / 5000.0
    profile_error = max((row["normalized_error"] for row in legacy_profile), default=math.inf)
    profile_monotonic = all(
        legacy_profile[index]["T_ANCF_N"] <= legacy_profile[index + 1]["T_ANCF_N"] +
        1.0e-10 * max(1.0, abs(legacy_profile[index]["T_ANCF_N"]),
                       abs(legacy_profile[index + 1]["T_ANCF_N"]))
        for index in range(len(legacy_profile) - 1)
    )
    invalid_results = _invalid_case_results(legacy_raw, output_dir)
    invalid_pass = all(item["status"] == "REJECT" for item in invalid_results)
    explicit_pass = all(value <= COMPARISON_TOLERANCE for value in explicit_comparison.values())
    caller_pass = all(value <= COMPARISON_TOLERANCE for value in caller_comparison.values())
    delta_agreement = abs(float(legacy_calibration["final_delta_length_m"]) - HISTORICAL_DELTA)
    status = "PASS" if all((
        legacy_calibration["bracket_valid"],
        target_error <= 1.0e-6,
        float(legacy_final["global_balance_error"]) <= 1.0e-10,
        delta_agreement <= 1.0e-8,
        legacy_initializer.omega_s > 0.0,
        explicit_pass, caller_pass, handoff["status"] == "PASS",
        handoff["q_match"], handoff["qdot_zero"], handoff["qddot_zero"],
        artifact_validation["time_s"] == 0.0,
        artifact_validation["global_step"] == 0,
        invalid_pass, profile_error <= 1.0e-4, profile_monotonic,
        legacy_initializer.potential_non_descent_failures == 0,
        legacy_initializer.potential_line_search_failures == 0,
        legacy_initializer.unchanged_trials_accepted == 0,
    )) else "FAIL"
    result = {
        "status": status,
        "primary_failure": None if status == "PASS" else "FROZEN_GATE_FAILURE",
        "protocol_sha256": PROTOCOL_SHA256,
        "production_commit": BASELINE_COMMIT,
        "legacy_calibration": {
            "DeltaL_final_m": legacy_calibration["final_delta_length_m"],
            "H_final_m": legacy_calibration["final"]["height_m"],
            "T_top_final_N": legacy_final["top_tension_N"],
            "target_relative_error": target_error,
            "historical_DeltaL_m": HISTORICAL_DELTA,
            "historical_T_top_N": HISTORICAL_TOP,
            "DeltaL_agreement_abs_m": delta_agreement,
            "omega_s_N_per_m": legacy_initializer.omega_s,
            "top_reaction": legacy_final["top_reaction"],
            "bottom_reaction": legacy_final["bottom_reaction"],
            "external_total": legacy_final["external_total"],
            "global_balance_error": legacy_final["global_balance_error"],
            "max_abs_lambda_minus_1": legacy_final["max_abs_lambda_minus_1"],
            "static_solves": legacy_calibration["static_solves"],
            "total_newton_iterations": legacy_calibration["total_newton_iterations"],
            "potential_non_descent_failures": legacy_calibration["potential_non_descent_failures"],
            "potential_line_search_failures": legacy_calibration["potential_line_search_failures"],
            "minimum_accepted_beta": legacy_calibration["minimum_accepted_beta"],
            "maximum_backtrack_depth": legacy_calibration["maximum_backtrack_depth"],
            "unchanged_trials_seen": legacy_calibration["unchanged_trials_seen"],
            "unchanged_trials_accepted": legacy_calibration["unchanged_trials_accepted"],
        },
        "explicit_section_equivalence": {"status": "PASS" if explicit_pass else "FAIL",
                                          "comparison": explicit_comparison},
        "caller_model_static_equivalence": {"status": "PASS" if caller_pass else "FAIL",
                                            "comparison": caller_comparison},
        "tension_profile": {
            "status": "PASS" if profile_error <= 1.0e-4 and profile_monotonic else "FAIL",
            "sample_count": len(legacy_profile),
            "max_normalized_error": profile_error,
            "monotonic_bottom_to_top": profile_monotonic,
            "min_T_ANCF_N": min(row["T_ANCF_N"] for row in legacy_profile),
            "max_T_ANCF_N": max(row["T_ANCF_N"] for row in legacy_profile),
            "min_T_ref_N": min(row["T_ref_N"] for row in legacy_profile),
            "max_T_ref_N": max(row["T_ref_N"] for row in legacy_profile),
        },
        "artifact": {
            "path": str(artifact_path),
            "state_kind": artifact["state_kind"],
            "artifact_validation": "PASS",
            "case_config_sha256": artifact["case_config_sha256"],
            "resolved_static_model_identity_sha256": artifact["resolved_static_model_identity_sha256"],
        },
        "generic_participant_prestressed_start_handoff": handoff,
        "invalid_input_tests": {
            "total": len(invalid_results),
            "passed": sum(item["status"] == "REJECT" for item in invalid_results),
            "status": "PASS" if invalid_pass else "FAIL",
            "cases": invalid_results,
        },
        "forbidden_execution": {
            "production_modified": False,
            "worker_dynamic_run": False,
            "formal_G1_run": False,
            "formal_C_F_run": False,
            "MATLAB": False,
            "OpenFOAM": False,
            "preCICE": False,
            "CFD_FSI": False,
            "named_literature_case": False,
        },
        "historical_state_preserved": True,
        "independent_ANCF_validation": "NOT_COMPLETED",
    }
    _write_json(output_dir / "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_RESULT.json", result)
    with (output_dir / "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_TEST_RAW.txt").open(
            "w", encoding="utf-8") as handle:
        handle.write("ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1 frozen synthetic regression\n")
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        handle.write("\nCalibration history:\n")
        for row in legacy_calibration["history"]:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.write("\nExplicit comparison:\n" + json.dumps(explicit_comparison, sort_keys=True) + "\n")
        handle.write("Caller/model-static comparison:\n" + json.dumps(caller_comparison, sort_keys=True) + "\n")

    report = f"""# ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_PATCH — Report

## Final status

ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_PATCH = {status}

This is a generic synthetic static-prestress capability regression, not a
named-paper benchmark or independent ANCF validation.

## Result

- Production baseline: {BASELINE_COMMIT}
- Frozen protocol SHA-256: {PROTOCOL_SHA256}
- Strategy: installed_stretch_target_top_reaction
- Static path: production PotentialBacktrackingNewton plus
  FixedConservativeGeneralizedLoad
- omega_s: {legacy_initializer.omega_s:.17g} N/m
- Bracket valid: {legacy_calibration['bracket_valid']}
- DeltaL_final: {legacy_calibration['final_delta_length_m']:.17g} m
- H_final: {legacy_final['height_m']:.17g} m
- T_top_final: {legacy_final['top_tension_N']:.17g} N
- Relative target error: {target_error:.17g}
- Historical DeltaL agreement: {delta_agreement:.17g} m
- Global balance error: {legacy_final['global_balance_error']:.17g}
- Tension profile error: {profile_error:.17g}
- Tension monotonic bottom-to-top: {profile_monotonic}
- Maximum abs(lambda-1): {legacy_final['max_abs_lambda_minus_1']:.17g}

Legacy and explicit-section calibrations agree under the frozen comparison
gate: {explicit_pass}. Model-static and caller-supplied canonical base-load
calibrations agree: {caller_pass}.

The generated artifact has state_kind prestressed_static; generic participant
prestressed_start loading validated q, zero qdot/qddot, time 0, step 0, and
the resolved final boundary. Invalid-input tests:
{len(invalid_results)}/{sum(item['status'] == 'REJECT' for item in invalid_results)}
rejected deterministically.

No production source, worker dynamic path, formal G1/C/F, MATLAB, OpenFOAM,
preCICE, CFD/FSI, or named literature case was run.

Historical status remains G1-V1.2 = FAIL retained and
independent ANCF validation = NOT_COMPLETED.
"""
    (output_dir / "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_PATCH_REPORT.md").write_text(
        report, encoding="utf-8")
    return result


V12_RESULT_PREFIX = "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1.2"


def _write_v12_empty_history(path: Path) -> None:
    fields = [
        "evaluation_id", "bisection_iteration", "DeltaL_m", "H_m", "lambda0",
        "epsilon0", "static_status", "static_Newton_iterations", "T_top_N",
        "f_N", "relative_target_error", "top_Rx_N", "top_Ry_N", "top_Rz_N",
        "bottom_Rx_N", "bottom_Ry_N", "bottom_Rz_N",
    ]
    path.write_text(",".join(fields) + "\n", encoding="utf-8")


def _write_v12_empty_profile(path: Path) -> None:
    path.write_text(
        "s_ref_m,current_z_m,lambda,epsilon,T_ANCF_N,T_ref_N,difference_N,normalized_error\n",
        encoding="utf-8")


def _persist_helper_streams(evidence_dir: Path, output_dir: Path) -> None:
    for suffix, filename in (("stdout", f"{V12_RESULT_PREFIX}_HELPER_STDOUT.txt"),
                             ("stderr", f"{V12_RESULT_PREFIX}_HELPER_STDERR.txt")):
        paths = sorted(evidence_dir.glob(f"eval-*.{suffix}.txt"))
        chunks = []
        for path in paths:
            chunks.append(f"===== {path.name} =====\n{path.read_text(encoding='utf-8')}\n")
        (output_dir / filename).write_text(
            "".join(chunks) if chunks else "NO_FORMAL_HELPER_STREAM_CAPTURED\n",
            encoding="utf-8")


def _run_transport_case(driver: Path, evidence_dir: Path, case: str,
                        evaluation_id: str) -> dict[str, Any]:
    result_path = evidence_dir / f"{evaluation_id}.result.json"
    command = [str(driver), "--result-json", str(result_path),
               "--evaluation-id", evaluation_id, "--transport-self-test", case]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    row: dict[str, Any] = {
        "case": case, "evaluation_id": evaluation_id,
        "returncode": completed.returncode,
        "stdout": completed.stdout, "stderr": completed.stderr,
        "result_path": str(result_path),
    }
    return row


def run_transport_only(driver: Path, output_dir: Path) -> dict[str, Any]:
    """Run T1-T12 without invoking static_equilibrium()."""
    evidence_dir = output_dir / f"{V12_RESULT_PREFIX}_TRANSPORT_EVIDENCE"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    def run_valid(case: str, identifier: str) -> Mapping[str, Any]:
        row = _run_transport_case(driver, evidence_dir, case, identifier)
        result = read_result_file(evidence_dir / f"{identifier}.result.json", identifier,
                                  allow_transport_test=True)
        row["result_status"] = result.get("status")
        rows.append(row)
        return result

    run_valid("valid", "transport-01")
    stdout_result = run_valid("stdout_diagnostic", "transport-02")
    if not stdout_result or not rows[-1]["stdout"]:
        raise PrestressError("TRANSPORT_TEST_FAIL: stdout diagnostic was not captured")
    stderr_result = run_valid("stderr_diagnostic", "transport-03")
    if not stderr_result or not rows[-1]["stderr"]:
        raise PrestressError("TRANSPORT_TEST_FAIL: stderr diagnostic was not captured")
    for index, case in enumerate(("nan", "inf", "neginf"), start=4):
        identifier = f"transport-{index:02d}"
        row = _run_transport_case(driver, evidence_dir, case, identifier)
        result = read_result_file(evidence_dir / f"{identifier}.result.json", identifier)
        if row["returncode"] != 3 or result.get("status") != "FAIL" or \
                result.get("failure_classification") != "NONFINITE_STATIC_RESULT":
            raise PrestressError(f"TRANSPORT_TEST_FAIL: {case}")
        row["result_status"] = result.get("status")
        row["failure_classification"] = result.get("failure_classification")
        rows.append(row)

    missing = subprocess.run(
        [str(driver), "--evaluation-id", "transport-07", "--transport-self-test", "valid"],
        capture_output=True, text=True, check=False)
    rows.append({"case": "missing_result_path", "returncode": missing.returncode,
                 "stdout": missing.stdout, "stderr": missing.stderr})
    if missing.returncode != 2:
        raise PrestressError("TRANSPORT_TEST_FAIL: missing result path")

    parent_file = evidence_dir / "transport-unwritable-parent.marker"
    parent_file.write_text("not a directory", encoding="utf-8")
    unwritable_path = parent_file / "result.json"
    unwritable = subprocess.run(
        [str(driver), "--result-json", str(unwritable_path),
         "--evaluation-id", "transport-08", "--transport-self-test", "valid"],
        capture_output=True, text=True, check=False)
    rows.append({"case": "unwritable_output", "returncode": unwritable.returncode,
                 "stdout": unwritable.stdout, "stderr": unwritable.stderr})
    if unwritable.returncode != 4:
        raise PrestressError("TRANSPORT_TEST_FAIL: unwritable output")

    run_valid("replace", "transport-09")
    try:
        read_result_file(evidence_dir / "transport-01.result.json", "wrong-id")
    except PrestressError as exc:
        rows.append({"case": "evaluation_id_mismatch", "status": "REJECT", "reason": str(exc)})
    else:
        raise PrestressError("TRANSPORT_TEST_FAIL: evaluation id mismatch")

    run_valid("valid", "transport-stale")
    try:
        read_result_file(evidence_dir / "transport-stale.result.json", "transport-current")
    except PrestressError as exc:
        rows.append({"case": "stale_result", "status": "REJECT", "reason": str(exc)})
    else:
        raise PrestressError("TRANSPORT_TEST_FAIL: stale result")

    partial = evidence_dir / "transport-partial.result.json"
    partial_tmp = evidence_dir / "transport-partial.result.json.tmp.transport-11"
    partial_tmp.write_text('{"schema_version":"ANCF_STATIC_PRESTRESS_RESULT_V1.2"', encoding="utf-8")
    try:
        read_result_file(partial, "transport-11")
    except PrestressError as exc:
        rows.append({"case": "partial_temp_not_accepted", "status": "REJECT", "reason": str(exc)})
    else:
        raise PrestressError("TRANSPORT_TEST_FAIL: partial temp accepted")

    roundtrip = run_valid("valid", "transport-12")
    if roundtrip.get("evaluation_id") != "transport-12":
        raise PrestressError("TRANSPORT_TEST_FAIL: evaluation id round-trip")

    summary = {"status": "PASS", "total": len(rows), "passed": len(rows), "cases": rows}
    (output_dir / f"{V12_RESULT_PREFIX}_TRANSPORT_TEST_RAW.txt").write_text(
        "ANCF V1.2 transport-only evidence; no static_equilibrium call\n" +
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _fresh_offline_suite() -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "discover", "-s",
               "tools/precice_ancf_adapter_v1/tests", "-p", "test_*.py", "-q"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False,
                               env={**dict(__import__("os").environ),
                                    "PYTHONPATH": f"{ROOT};{ROOT / 'src'}"})
    return {"status": "PASS" if completed.returncode == 0 else "FAIL",
            "returncode": completed.returncode, "stdout": completed.stdout,
            "stderr": completed.stderr}


def _write_v12_failure(output_dir: Path, failure: str, transport: Mapping[str, Any],
                       offline: Mapping[str, Any], evidence_dir: Path) -> dict[str, Any]:
    _write_v12_empty_history(output_dir / f"{V12_RESULT_PREFIX}_HISTORY.csv")
    _write_v12_empty_profile(output_dir / f"{V12_RESULT_PREFIX}_PROFILE.csv")
    _persist_helper_streams(evidence_dir, output_dir)
    classification = failure.split(":", 1)[0]
    result = {
        "status": "FAIL", "primary_failure": classification,
        "failure_detail": failure, "protocol_sha256": PROTOCOL_SHA256,
        "production_commit": BASELINE_COMMIT,
        "historical_v1_status": "FAIL / STATIC_SOLVE_FAIL",
        "historical_v1_1_status": "STOPPED_BEFORE_PROTOCOL / V1_RAW_EVIDENCE_INSUFFICIENT",
        "transport_tests": dict(transport), "offline_tests": dict(offline),
        "legacy_calibration": {"status": "NOT_COMPLETED"},
        "high_bracket": {"status": "NOT_REACHED"},
        "bisection_iterations": 0, "final_DeltaL_m": None,
        "final_H_m": None, "final_T_top_N": None,
        "target_relative_error": None, "top_reaction": None,
        "bottom_reaction": None, "global_balance_error": None,
        "potential_diagnostics": {"status": "NOT_OBTAINED"},
        "explicit_section_equivalence": "NOT_RUN",
        "caller_model_static_equivalence": "NOT_RUN",
        "static_state_artifact": "NOT_GENERATED",
        "generic_participant_prestressed_start_handoff": "NOT_RUN",
        "forbidden_execution": {
            "production_modified": False, "formal_G1_run": False,
            "formal_C_F_run": False, "worker_dynamic_run": False,
            "MATLAB": False, "OpenFOAM": False, "preCICE": False,
            "CFD_FSI": False, "named_literature_case": False,
        },
        "historical_state_preserved": True,
        "independent_ANCF_validation": "NOT_COMPLETED",
    }
    _write_json(output_dir / f"{V12_RESULT_PREFIX}_PATCH_RESULT.json", result)
    raw = "ANCF V1.2 stopped before successful static result\n" + json.dumps(
        result, indent=2, sort_keys=True) + "\n"
    (output_dir / f"{V12_RESULT_PREFIX}_TEST_RAW.txt").write_text(raw, encoding="utf-8")
    report = f"""# {V12_RESULT_PREFIX} — Failure Report

Status: `FAIL`

Primary frozen failure: `{classification}`

Failure detail: `{failure}`

The V1 exact malformed stdout token remains unrecoverable. V1.2 used the
result-file transport only. The run stopped at the first applicable failure;
no retry was performed.

Transport tests: {transport.get('passed', 0)}/{transport.get('total', 0)}.
Offline suite: {offline.get('status')}.
No explicit-section, caller/model-static, artifact, or participant handoff
gate was run after this failure.

Protected kernel, worker, wire, historical states, and V1/V1.1 evidence were
preserved. No G1, formal C/F, worker dynamic, preCICE, OpenFOAM, CFD/FSI,
MATLAB, or literature case was run.
"""
    (output_dir / f"{V12_RESULT_PREFIX}_PATCH_REPORT.md").write_text(report, encoding="utf-8")
    return result


def run_v12(output_dir: Path, driver: Path, transport: Mapping[str, Any],
            offline: Mapping[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = output_dir / f"{V12_RESULT_PREFIX}_EVIDENCE"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    state_name = f"{V12_RESULT_PREFIX}_STATIC_STATE.json"
    legacy_raw = make_synthetic_case(state_file=state_name)
    legacy_config = _config(legacy_raw, output_dir)
    legacy_initializer = StaticPrestressInitializer(
        legacy_config, driver, result_directory=evidence_dir / "legacy")
    try:
        legacy_calibration = legacy_initializer.calibrate()
    except PrestressError as exc:
        return _write_v12_failure(output_dir, str(exc), transport, offline, evidence_dir / "legacy")

    legacy_final = legacy_calibration["final"]
    legacy_profile = legacy_initializer.tension_profile(legacy_final)
    legacy_initializer.write_history(output_dir / f"{V12_RESULT_PREFIX}_HISTORY.csv")
    with (output_dir / f"{V12_RESULT_PREFIX}_PROFILE.csv").open(
            "w", encoding="utf-8", newline="") as handle:
        import csv
        fields = ["s_ref_m", "current_z_m", "lambda", "epsilon",
                  "T_ANCF_N", "T_ref_N", "difference_N", "normalized_error"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(legacy_profile)
    _persist_helper_streams(evidence_dir / "legacy", output_dir)

    artifact = legacy_initializer.make_static_artifact(
        legacy_calibration, PROTOCOL_SHA256, BASELINE_COMMIT)
    artifact_path = output_dir / state_name
    _write_json(artifact_path, artifact)
    artifact_validation = legacy_config.initial_state()
    handoff = _fake_handoff(legacy_config)
    if tuple(artifact_validation["q"]) != tuple(artifact["q"]):
        raise PrestressError("STATIC_ARTIFACT_IDENTITY_FAIL")

    explicit_raw = deepcopy(legacy_raw)
    explicit_raw["section"]["mode"] = "explicit"
    explicit_config = _config(explicit_raw, output_dir)
    explicit_calibration = StaticPrestressInitializer(
        explicit_config, driver, result_directory=evidence_dir / "explicit").calibrate()

    caller_raw = deepcopy(legacy_raw)
    caller_raw["base_load"] = {
        "source": "caller_supplied",
        "vector": list(legacy_calibration["bracket_low"]["base_load"]),
    }
    caller_config = _config(caller_raw, output_dir)
    caller_calibration = StaticPrestressInitializer(
        caller_config, driver, result_directory=evidence_dir / "caller").calibrate()

    explicit_comparison = compare_calibrations(legacy_calibration, explicit_calibration)
    caller_comparison = compare_calibrations(legacy_calibration, caller_calibration)
    target_error = abs(float(legacy_final["top_tension_N"]) - 5000.0) / 5000.0
    profile_error = max((row["normalized_error"] for row in legacy_profile), default=math.inf)
    profile_monotonic = all(
        legacy_profile[index]["T_ANCF_N"] <= legacy_profile[index + 1]["T_ANCF_N"] +
        1.0e-10 * max(1.0, abs(legacy_profile[index]["T_ANCF_N"]),
                       abs(legacy_profile[index + 1]["T_ANCF_N"]))
        for index in range(len(legacy_profile) - 1))
    invalid_results = _invalid_case_results(legacy_raw, output_dir)
    invalid_pass = all(item["status"] == "REJECT" for item in invalid_results)
    explicit_pass = all(value <= COMPARISON_TOLERANCE for value in explicit_comparison.values())
    caller_pass = all(value <= COMPARISON_TOLERANCE for value in caller_comparison.values())
    delta_agreement = abs(float(legacy_calibration["final_delta_length_m"]) - HISTORICAL_DELTA)
    status = "PASS" if all((
        legacy_calibration["bracket_valid"], target_error <= 1.0e-6,
        float(legacy_final["global_balance_error"]) <= 1.0e-10,
        delta_agreement <= 1.0e-8, legacy_initializer.omega_s > 0.0,
        explicit_pass, caller_pass, handoff["status"] == "PASS",
        handoff["q_match"], handoff["qdot_zero"], handoff["qddot_zero"],
        artifact_validation["time_s"] == 0.0, artifact_validation["global_step"] == 0,
        invalid_pass, profile_error <= 1.0e-4, profile_monotonic,
        legacy_initializer.potential_non_descent_failures == 0,
        legacy_initializer.potential_line_search_failures == 0,
        legacy_initializer.unchanged_trials_accepted == 0,
    )) else "FAIL"
    result = {
        "status": status, "primary_failure": None if status == "PASS" else "FROZEN_GATE_FAILURE",
        "protocol_sha256": PROTOCOL_SHA256, "production_commit": BASELINE_COMMIT,
        "historical_v1_status": "FAIL / STATIC_SOLVE_FAIL",
        "historical_v1_1_status": "STOPPED_BEFORE_PROTOCOL / V1_RAW_EVIDENCE_INSUFFICIENT",
        "transport_tests": dict(transport), "offline_tests": dict(offline),
        "legacy_calibration": {
            "DeltaL_final_m": legacy_calibration["final_delta_length_m"],
            "H_final_m": legacy_final["height_m"], "T_top_final_N": legacy_final["top_tension_N"],
            "target_relative_error": target_error, "historical_DeltaL_m": HISTORICAL_DELTA,
            "historical_T_top_N": HISTORICAL_TOP, "DeltaL_agreement_abs_m": delta_agreement,
            "omega_s_N_per_m": legacy_initializer.omega_s,
            "top_reaction": legacy_final["top_reaction"], "bottom_reaction": legacy_final["bottom_reaction"],
            "external_total": legacy_final["external_total"],
            "global_balance_error": legacy_final["global_balance_error"],
            "static_solves": legacy_calibration["static_solves"],
            "total_newton_iterations": legacy_calibration["total_newton_iterations"],
            "potential_non_descent_failures": legacy_calibration["potential_non_descent_failures"],
            "potential_line_search_failures": legacy_calibration["potential_line_search_failures"],
            "minimum_accepted_beta": legacy_calibration["minimum_accepted_beta"],
            "maximum_backtrack_depth": legacy_calibration["maximum_backtrack_depth"],
            "unchanged_trials_seen": legacy_calibration["unchanged_trials_seen"],
            "unchanged_trials_accepted": legacy_calibration["unchanged_trials_accepted"],
        },
        "bracket": {
            "low": legacy_calibration["bracket_low"],
            "high": legacy_calibration["bracket_high"],
            "valid": legacy_calibration["bracket_valid"],
        },
        "bisection_iterations": max((row["bisection_iteration"] for row in legacy_calibration["history"]), default=0),
        "final_DeltaL_m": legacy_calibration["final_delta_length_m"],
        "final_H_m": legacy_final["height_m"], "final_T_top_N": legacy_final["top_tension_N"],
        "target_relative_error": target_error, "top_reaction": legacy_final["top_reaction"],
        "bottom_reaction": legacy_final["bottom_reaction"],
        "global_balance_error": legacy_final["global_balance_error"],
        "potential_diagnostics": legacy_calibration,
        "explicit_section_equivalence": {"status": "PASS" if explicit_pass else "FAIL",
                                          "comparison": explicit_comparison},
        "caller_model_static_equivalence": {"status": "PASS" if caller_pass else "FAIL",
                                             "comparison": caller_comparison},
        "static_state_artifact": {"status": "PASS", "path": str(artifact_path),
                                   "state_kind": artifact["state_kind"],
                                   "case_config_sha256": artifact["case_config_sha256"],
                                   "model_identity_sha256": artifact["model_identity_sha256"]},
        "generic_participant_prestressed_start_handoff": handoff,
        "invalid_input_tests": {"total": len(invalid_results),
                                 "passed": sum(item["status"] == "REJECT" for item in invalid_results),
                                 "status": "PASS" if invalid_pass else "FAIL", "cases": invalid_results},
        "forbidden_execution": {
            "production_modified": False, "worker_dynamic_run": False,
            "formal_G1_run": False, "formal_C_F_run": False, "MATLAB": False,
            "OpenFOAM": False, "preCICE": False, "CFD_FSI": False,
            "named_literature_case": False,
        },
        "historical_state_preserved": True, "independent_ANCF_validation": "NOT_COMPLETED",
    }
    _write_json(output_dir / f"{V12_RESULT_PREFIX}_PATCH_RESULT.json", result)
    (output_dir / f"{V12_RESULT_PREFIX}_TEST_RAW.txt").write_text(
        "ANCF V1.2 generic static-prestress regression\n" +
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = f"""# {V12_RESULT_PREFIX} — Report

Status: `{status}`

V1.2 replaces stdout machine parsing with the result-file contract
`{RESULT_SCHEMA_VERSION}`. The exact V1 malformed stdout token remains
unrecoverable and is not reclassified.

- Protocol SHA-256: `{PROTOCOL_SHA256}`
- Legacy DeltaL: `{legacy_calibration['final_delta_length_m']:.17g} m`
- Legacy H: `{legacy_final['height_m']:.17g} m`
- Legacy top tension: `{legacy_final['top_tension_N']:.17g} N`
- Target relative error: `{target_error:.17g}`
- Global balance error: `{legacy_final['global_balance_error']:.17g}`
- Explicit equivalence: `{explicit_pass}`
- Caller/model-static equivalence: `{caller_pass}`
- Artifact and handoff: `{artifact['state_kind']}`, `{handoff['status']}`
- Transport tests: `{transport.get('passed', 0)}/{transport.get('total', 0)}`
- Offline suite: `{offline.get('status')}`

No G1, formal C/F, worker dynamic, preCICE, OpenFOAM, CFD/FSI, MATLAB, or
named-literature case was run. Historical V1/V1.1 states remain unchanged.
"""
    (output_dir / f"{V12_RESULT_PREFIX}_PATCH_REPORT.md").write_text(report, encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--transport-only":
        summary = run_transport_only(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
        print(json.dumps(summary, sort_keys=True))
        raise SystemExit(0 if summary["status"] == "PASS" else 1)
    if len(sys.argv) == 4 and sys.argv[1] == "--v1.2":
        driver = Path(sys.argv[2]).resolve()
        output_dir = Path(sys.argv[3]).resolve()
        try:
            transport_summary = run_transport_only(driver, output_dir)
            offline_summary = _fresh_offline_suite()
            if offline_summary["status"] != "PASS":
                result = _write_v12_failure(
                    output_dir, "UNIT_TEST_FAIL", transport_summary, offline_summary,
                    output_dir / f"{V12_RESULT_PREFIX}_EVIDENCE" / "legacy")
            else:
                result = run_v12(output_dir, driver, transport_summary, offline_summary)
        except (PrestressError, OSError, ValueError) as exc:
            result = _write_v12_failure(
                output_dir, str(exc), locals().get("transport_summary", {"status": "FAIL"}),
                locals().get("offline_summary", {"status": "NOT_RUN"}),
                output_dir / f"{V12_RESULT_PREFIX}_EVIDENCE" / "legacy")
        print(json.dumps({"status": result["status"],
                          "primary_failure": result.get("primary_failure"),
                          "final_DeltaL_m": result.get("final_DeltaL_m")}, sort_keys=True))
        raise SystemExit(0 if result["status"] == "PASS" else 1)
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_static_prestress_regression_v1.py <driver.exe> <output-dir> | --transport-only <driver.exe> <output-dir> | --v1.2 <driver.exe> <output-dir>")
    output = run(Path(sys.argv[2]).resolve(), Path(sys.argv[1]).resolve())
    print(json.dumps({"status": output["status"],
                      "DeltaL_final_m": output["legacy_calibration"]["DeltaL_final_m"],
                      "T_top_final_N": output["legacy_calibration"]["T_top_final_N"]},
                     sort_keys=True))
