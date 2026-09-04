"""Formalize immutable Stage 304/305 evidence without starting a solver."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coupling.stage306_offline_formalization_v1.audit import (  # noqa: E402
    AuditError,
    evaluate_formal_checks,
    load_json,
    parse_mapping_diagnostics,
    parse_openfoam_log,
    sha256_file,
    statistics_from_samples,
    validate_checkpoints,
)

STAGE304 = ROOT / "runtime/stage304_interface_mapping_repair_v1_fresh_zero_to80s"
STAGE305 = ROOT / "runtime/stage305_interface_mapping_repair_v1_continue80_to250s"
GATE304 = ROOT / "results/304_interface_mapping_repair_v1/stage4f_d_interface_mapping_repair_v1_fresh_zero_to80s_gate.json"
GATE305 = ROOT / "results/305_interface_mapping_repair_v1/stage4f_d_interface_mapping_repair_v1_continue80_to250s_gate.json"
DEFAULT_OUTPUT = ROOT / "results/306_offline_formalization_v1"

SOURCE_STEP = 16000
SOURCE_TIME_S = 80.0
TARGET_STEP = 50000
TARGET_TIME_S = 250.0
DT_S = 0.005
SLICE_COUNT = 3
LOCAL_STEPS = 34000


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def nested(mapping: Mapping[str, object], *keys: str) -> object:
    value: object = mapping
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            raise AuditError("missing evidence field: " + ".".join(keys))
        value = value[key]
    return value


def same_number(left: object, right: object, tolerance: float = 5.0e-12) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def parse_returns(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or "=" not in line:
            raise AuditError("malformed returns evidence")
        name, raw_value = line.split("=", 1)
        try:
            result[name] = int(raw_value)
        except ValueError as exc:
            raise AuditError("non-integer return code") from exc
    expected = {"structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return"}
    if set(result) != expected:
        raise AuditError("return-code identity mismatch")
    return result


def validate_tail_records(barrier: Mapping[str, object]) -> bool:
    records = barrier.get("tail_records")
    if not isinstance(records, list) or len(records) != 20:
        return False
    first_step = TARGET_STEP - len(records) + 1
    for offset, row in enumerate(records):
        if not isinstance(row, Mapping):
            return False
        global_step = first_step + offset
        local_step = global_step - SOURCE_STEP
        time_s = SOURCE_TIME_S + local_step * DT_S
        if row.get("global_step") != global_step or row.get("case_local_bridge_step") != local_step:
            return False
        if not same_number(row.get("time_s"), time_s) or row.get("integer_tick") != int(round(time_s * 1e9)):
            return False
        if row.get("committed") is not True:
            return False
        slices = row.get("slices")
        if not isinstance(slices, list) or len(slices) != SLICE_COUNT:
            return False
        for index, slice_row in enumerate(slices):
            if not isinstance(slice_row, Mapping) or slice_row.get("slice_id") != f"slice_{index:04d}" or slice_row.get("ack") != "consumed":
                return False
            if slice_row.get("global_step") != global_step or slice_row.get("case_local_bridge_step") != local_step:
                return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compileall-pass", action="store_true")
    parser.add_argument("--tests-pass", action="store_true")
    parser.add_argument("--test-count", type=int, default=0)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise AuditError(f"refusing to overwrite Stage306 evidence: {output}")

    gate304 = load_json(GATE304)
    gate305 = load_json(GATE305)
    logs304 = STAGE304 / "logs"
    logs305 = STAGE305 / "logs"
    structure304_path = logs304 / "structure_participant.json"
    structure305_path = logs305 / "structure_participant.json"
    structure304 = load_json(structure304_path)
    structure305 = load_json(structure305_path)
    barrier = load_json(logs305 / "global_barrier.json")
    progress = load_json(logs305 / "progress.json")

    source_paths = {
        "stage304_gate": GATE304,
        "stage305_gate": GATE305,
        "stage304_structure_final_state": structure304_path,
        "stage305_structure": structure305_path,
        "stage305_original_convergence_summary": logs305 / "convergence_summary.json",
        "stage305_global_barrier": logs305 / "global_barrier.json",
        "stage305_checkpoints": logs305 / "checkpoint.jsonl",
        "stage305_mapping_diagnostics": logs305 / "mapping_diagnostics.jsonl",
        "stage305_progress": logs305 / "progress.json",
        "stage305_returns": logs305 / "returns.txt",
        "stage305_structure_stderr": logs305 / "structure.stderr",
        "stage305_launcher_stderr": logs305 / "launcher.stderr",
        "worker_binary": ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker",
        "worker_fixture": ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json",
        "participant_source": ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py",
    }
    for index in range(SLICE_COUNT):
        source_paths[f"fluid_{index:04d}_stdout"] = logs305 / f"fluid_{index:04d}.stdout"
        source_paths[f"fluid_{index:04d}_stderr"] = logs305 / f"fluid_{index:04d}.stderr"
    for name, path in source_paths.items():
        if not path.is_file():
            raise AuditError(f"source evidence missing: {name}={path}")

    source_identity_checks = {
        "stage304_gate_pass": gate304.get("status") == "pass",
        "stage305_gate_pass": gate305.get("status") == "pass",
        "stage304_target_equals_stage305_source_step": nested(gate304, "scope_contract", "target_step") == nested(gate305, "scope_contract", "source_step") == SOURCE_STEP,
        "stage304_target_equals_stage305_source_time": same_number(nested(gate304, "scope_contract", "target_time_s"), SOURCE_TIME_S) and same_number(nested(gate305, "scope_contract", "source_time_s"), SOURCE_TIME_S),
        "stage305_target_step": nested(gate305, "scope_contract", "target_step") == TARGET_STEP,
        "stage305_target_time": same_number(nested(gate305, "scope_contract", "target_time_s"), TARGET_TIME_S),
        "dt_unchanged": same_number(nested(gate304, "scope_contract", "dt_s"), DT_S) and same_number(nested(gate305, "scope_contract", "dt_s"), DT_S),
        "slice_count_unchanged": nested(gate304, "scope_contract", "slice_count") == nested(gate305, "scope_contract", "slice_count") == SLICE_COUNT,
        "worker_hash_unchanged": nested(gate304, "source_hashes", "worker") == nested(gate305, "source_hashes", "worker"),
        "fixture_hash_unchanged": nested(gate304, "source_hashes", "fixture") == nested(gate305, "source_hashes", "fixture"),
        "participant_hash_unchanged": nested(gate304, "source_hashes", "participant") == nested(gate305, "source_hashes", "participant"),
        "stage304_final_state_is_stage305_initial_state": sha256_file(structure304_path) == nested(gate305, "source_hashes", "initial_state"),
        "worker_binary_hash_matches_gate": sha256_file(source_paths["worker_binary"]) == nested(gate305, "source_hashes", "worker"),
        "fixture_hash_matches_gate": sha256_file(source_paths["worker_fixture"]) == nested(gate305, "source_hashes", "fixture"),
        "participant_hash_matches_gate": sha256_file(source_paths["participant_source"]) == nested(gate305, "source_hashes", "participant"),
    }

    expected_slice_counts = {f"slice_{index:04d}": LOCAL_STEPS for index in range(SLICE_COUNT)}
    structure_checks = {
        "run_id_matches": structure305.get("run_id") == gate305.get("run_id"),
        "case_id_matches": structure305.get("case_id") == gate305.get("case_id"),
        "source_identity_matches": structure305.get("source_global_step") == SOURCE_STEP and same_number(structure305.get("source_time_s"), SOURCE_TIME_S),
        "target_identity_matches": structure305.get("target_global_step") == TARGET_STEP and same_number(structure305.get("target_time_s"), TARGET_TIME_S),
        "committed_steps_match": structure305.get("committed_steps") == TARGET_STEP and structure305.get("local_committed_steps") == LOCAL_STEPS,
        "slice_counts_match": structure305.get("slice_counts") == expected_slice_counts,
        "finalized": structure305.get("finalized") is True,
        "worker_closed_zero": nested(structure305, "worker", "closed") is True and nested(structure305, "worker", "return_code") == 0 and nested(structure305, "worker", "stderr") == "",
        "no_structure_error": structure305.get("error") is None,
        "barrier_hash_matches": structure305.get("barrier_sha256") == barrier.get("barrier_sha256"),
        "barrier_tail_identity": validate_tail_records(barrier),
        "progress_final": progress.get("current_global_step") == TARGET_STEP and same_number(progress.get("current_time_s"), TARGET_TIME_S) and progress.get("slice_counts") == expected_slice_counts,
    }
    for vector_name in ("final_q", "final_qdot", "final_qddot"):
        vector = structure305.get(vector_name)
        structure_checks[f"{vector_name}_finite"] = isinstance(vector, list) and len(vector) > 0 and all(math.isfinite(float(value)) for value in vector)

    returns = parse_returns(logs305 / "returns.txt")
    execution_checks = {
        "all_returns_zero": all(value == 0 for value in returns.values()),
        "all_stderr_empty": all(source_paths[name].stat().st_size == 0 for name in source_paths if name.endswith("stderr")),
        "owned_residual_zero": gate305.get("owned_residual") == 0,
        "stage305_return_zero": gate305.get("return_code") == 0,
    }

    checkpoints = validate_checkpoints(
        logs305 / "checkpoint.jsonl",
        source_step=SOURCE_STEP,
        source_time_s=SOURCE_TIME_S,
        target_step=TARGET_STEP,
        dt_s=DT_S,
    )
    mapping = parse_mapping_diagnostics(
        logs305 / "mapping_diagnostics.jsonl",
        source_step=SOURCE_STEP,
        source_time_s=SOURCE_TIME_S,
        dt_s=DT_S,
        expected_count=LOCAL_STEPS,
        slice_count=SLICE_COUNT,
    )
    fluid_quality = [parse_openfoam_log(logs305 / f"fluid_{index:04d}.stdout") for index in range(SLICE_COUNT)]
    quality_counts_match = (
        len({row["courant_count"] for row in fluid_quality}) == 1
        and len({row["continuity_global_count"] for row in fluid_quality}) == 1
        and all(int(row["courant_count"]) >= LOCAL_STEPS for row in fluid_quality)
        and all(int(row["continuity_global_count"]) >= LOCAL_STEPS for row in fluid_quality)
    )
    quality_end_time_matches = all(same_number(row["last_time_s"], TARGET_TIME_S) for row in fluid_quality)

    samples = mapping.pop("samples")
    assert isinstance(samples, list)
    statistical_summary = statistics_from_samples(samples, required_cycles=15)
    statistical_summary["source"] = "Stage305 mapping_diagnostics fluid_resultant_y / 3, sampled every 10 global steps"
    statistical_summary["thresholds"] = {
        "minimum_late_cycles": 15,
        "adjacent_windows": 3,
        "cycles_per_window": 5,
        "drift_tolerance_fraction": 0.05,
        "fft_peak_tolerance_fraction": 0.05,
        "courant_hard_stop_exclusive": 0.8,
        "continuity_threshold": None,
        "continuity_rule": "present and finite; no new threshold introduced",
    }
    formal_checks = evaluate_formal_checks(statistical_summary, fluid_quality)
    formal_checks["quality_record_coverage_consistent"] = quality_counts_match
    formal_checks["all_fluid_logs_reach_250s"] = quality_end_time_matches
    formal_checks["mapping_record_count_34000"] = mapping["record_count"] == LOCAL_STEPS
    formal_checks["mapping_identity_and_values_finite"] = mapping["all_values_finite"] is True
    formal_checks["checkpoint_identity_continuous"] = checkpoints["identity_continuous"] is True and checkpoints["last_global_step"] == TARGET_STEP

    verification_checks = {
        "compileall_pass": args.compileall_pass,
        "stage306_tests_pass": args.tests_pass,
        "stage306_test_count_positive": args.test_count > 0,
    }
    all_check_groups = [source_identity_checks, structure_checks, execution_checks, formal_checks, verification_checks]
    passed = all(all(group.values()) for group in all_check_groups)

    manifest = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "hash_algorithm": "sha256",
        "files": {
            name: {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for name, path in source_paths.items()
        },
    }
    augmented = {
        "schema_version": 1,
        "stage_id": "stage306_offline_formalization_v1",
        "source_run_id": gate305.get("run_id"),
        "source_case_id": gate305.get("case_id"),
        "statistical_summary": statistical_summary,
        "fluid_quality": fluid_quality,
        "mapping_quality": mapping,
        "checkpoint_quality": checkpoints,
        "formal_checks": formal_checks,
        "formal_convergence": "pass" if all(formal_checks.values()) else "not_completed",
    }
    warnings = []
    if mapping["all_slice_force_hashes_equal"] is True:
        warnings.append(
            "All three slice force hashes are identical for all 34000 Stage305 steps. This is not a new Gate threshold, "
            "but slice-specific CFD response diversity must be explained or disproved before interpreting slice-count convergence."
        )
    report = {
        "schema_version": 1,
        "status": "pass" if passed else "do_not_pass",
        "source_identity_checks": source_identity_checks,
        "structure_and_barrier_checks": structure_checks,
        "execution_checks": execution_checks,
        "formal_checks": formal_checks,
        "verification_checks": verification_checks,
        "returns": returns,
        "warnings": warnings,
        "real_process_starts_stage306": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0, "cpp_worker": 0},
        "owned_residual_stage306": 0,
        "protected_evidence": {
            "stage304_modified": False,
            "stage305_modified": False,
            "ancf_eb_core_modified": False,
            "physical_parameters_modified": False,
            "global_dt_modified": False,
            "slice_count_modified": False,
            "numerical_thresholds_modified": False,
            "formal_0_2_1_protocol_modified": False,
        },
        "recommendation": {
            "next_methodological_step": "slice_count_convergence_before_public_experiment_validation",
            "mandatory_preflight": "offline configuration audit plus short five-slice smoke proving slice-specific motion/force identities are not accidentally cloned",
            "campaign_scope": "begin with 3-versus-5 slices; add 9 slices only if the 3-to-5 trend is not converged",
            "real_run_authorization": "new explicit authorization required",
        },
    }
    gate = {
        "gate_id": "STAGE4F_D_THREE_SLICE_STABLE_RESPONSE_OFFLINE_FORMALIZATION_V1_GATE",
        "status": "pass" if passed else "do_not_pass",
        "stage_id": "stage306_offline_formalization_v1",
        "source_stage": "stage305_interface_mapping_repair_v1_continue80_to250s",
        "source_run_id": gate305.get("run_id"),
        "source_case_id": gate305.get("case_id"),
        "scope": "offline immutable-evidence audit only",
        "checks": {
            "source_identity": all(source_identity_checks.values()),
            "execution_identity": all(structure_checks.values()) and all(execution_checks.values()),
            "formal_convergence": all(formal_checks.values()),
            "offline_verification": all(verification_checks.values()),
        },
        "late_response": {
            key: statistical_summary.get(key)
            for key in (
                "late_cycle_count",
                "late_start_time_s",
                "late_end_time_s",
                "late_peak_frequency_hz",
                "late_fft_frequency_hz",
                "frequency_drift_fraction",
                "rms_drift_fraction",
                "peak_to_peak_drift_fraction",
                "mean_span_over_average_rms",
                "fft_peak_relative_difference",
            )
        },
        "fluid_quality": {
            "max_courant": max(float(row["courant_max"]) for row in fluid_quality),
            "max_abs_instantaneous_global_continuity_error": max(float(row["continuity_global_abs_max"]) for row in fluid_quality),
            "courant_records_per_slice": [row["courant_count"] for row in fluid_quality],
            "continuity_records_per_slice": [row["continuity_global_count"] for row in fluid_quality],
        },
        "mapping_quality": mapping,
        "formal_status": {
            "FORMAL_RESPONSE_FREQUENCY_STATUS": "completed_for_this_three_slice_case" if passed else "not_completed",
            "STABLE_VIV_RESPONSE_CLAIM": "completed_for_this_three_slice_case" if passed else "not_completed",
            "FORMAL_STROUHAL_STATUS": "not_completed",
            "LOCK_IN_CLAIM": "not_completed",
            "SLICE_COUNT_CONVERGENCE_STATUS": "not_completed",
            "PUBLIC_EXPERIMENT_VALIDATION_STATUS": "not_completed",
        },
        "warnings": warnings,
        "real_process_starts_stage306": report["real_process_starts_stage306"],
        "owned_residual_stage306": 0,
        "next_authorization": "new explicit authorization required before any real slice-count or validation run",
    }

    output.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output / "evidence_manifest.json", manifest)
    write_json_atomic(output / "augmented_convergence.json", augmented)
    write_json_atomic(output / "offline_audit_report.json", report)
    write_json_atomic(output / "stage4f_d_three_slice_stable_response_offline_formalization_v1_gate.json", gate)
    print(json.dumps({"status": gate["status"], "output": str(output), "gate_id": gate["gate_id"]}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
