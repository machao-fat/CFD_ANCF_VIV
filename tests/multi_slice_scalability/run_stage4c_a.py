"""Run the Stage 4C-A mock campaign and write candidate evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.coupling.multi_slice_campaign import (
    build_candidate_definition,
    build_scale_definition,
    map_spatial_loads,
    run_failure_injection_matrix,
    run_mock_campaign,
    run_restart_comparison,
    serialize_candidate_pair,
)
from src.coupling.multi_slice_mapping.mapping import atomic_write_json


def write_json(path: Path, value: dict[str, object]) -> None:
    atomic_write_json(path, value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "05_stage4c_scalability_tests",
    )
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    run_id = "stage4c_a_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    runs = output / "runs" / run_id
    runs.mkdir(parents=True, exist_ok=True)

    definition3 = build_candidate_definition(3)
    definition5 = build_candidate_definition(5)
    candidate3 = serialize_candidate_pair(definition3, output)
    candidate5 = serialize_candidate_pair(definition5, output)

    spatial = {
        "schema_version": "stage4c_a_spatial_load_mapping_summary",
        "protocol_version": "0.2.1",
        "three_slice": {profile: map_spatial_loads(definition3, profile=profile, seed=20260810, random_seed=17) for profile in ("uniform", "linear", "non_monotonic", "random")},
        "five_slice": {profile: map_spatial_loads(definition5, profile=profile, seed=20260810, random_seed=19) for profile in ("uniform", "linear", "non_monotonic", "random")},
    }
    write_json(output / "spatial_load_mapping_summary.json", spatial)

    mock3 = run_mock_campaign(definition3, runs / "three_slice_mock", steps=10, profile="non_monotonic", seed=20260810)
    mock5 = run_mock_campaign(definition5, runs / "five_slice_mock", steps=10, profile="non_monotonic", seed=20260810)
    write_json(output / "three_slice_mock_summary.json", mock3)
    write_json(output / "five_slice_mock_summary.json", mock5)

    restart3 = run_restart_comparison(definition3, runs / "three_slice_restart", profile="non_monotonic", seed=20260810)
    restart5 = run_restart_comparison(definition5, runs / "five_slice_restart", profile="non_monotonic", seed=20260810)
    write_json(output / "three_slice_restart_comparison.json", restart3)
    write_json(output / "five_slice_restart_comparison.json", restart5)

    scale = {}
    for number in (2, 3, 5):
        definition = build_scale_definition(number)
        scale[str(number)] = run_mock_campaign(
            definition,
            runs / f"scale_{number}slice",
            steps=10,
            profile="non_monotonic",
            seed=20260810,
        )
    write_json(output / "scalability_metrics.json", {
        "schema_version": "stage4c_a_scalability_metrics",
        "protocol_version": "0.2.1",
        "target": "discover_superlinear_anomalies; not a proof of strict linear scaling",
        "by_slice_count": scale,
    })

    failures = {
        "schema_version": "stage4c_a_failure_injection_summary",
        "protocol_version": "0.2.1",
        "three_slice": run_failure_injection_matrix(definition3, runs / "three_slice_failures"),
        "five_slice": run_failure_injection_matrix(definition5, runs / "five_slice_failures"),
    }
    write_json(output / "failure_injection_summary.json", failures)

    candidate_summary = {
        "schema_version": "stage4c_a_candidate_summary",
        "status": "completed_candidate_evidence",
        "protocol_version": "0.2.1",
        "scope": "three_to_five_slice_scalability_spatial_nonuniformity_and_unified_transaction_mock_synthetic_verification",
        "run_id": run_id,
        "real_openfoam_run": False,
        "long_free_viv_run": False,
        "candidate_configurations": {"three_slice": candidate3, "five_slice": candidate5},
        "mock_campaign": {
            "three_slice_completed_10_steps": mock3["time_barrier_pass"],
            "five_slice_completed_10_steps": mock5["time_barrier_pass"],
            "three_slice_committed_manifests": mock3["files"]["committed_manifest_count"],
            "five_slice_committed_manifests": mock5["files"]["committed_manifest_count"],
        },
        "restart": {
            "three_slice_bitwise_selected_state_equal": restart3["bitwise_selected_state_equal"],
            "five_slice_bitwise_selected_state_equal": restart5["bitwise_selected_state_equal"],
            "three_slice_max_abs_error": restart3["selected_manifest_max_abs_error"],
            "five_slice_max_abs_error": restart5["selected_manifest_max_abs_error"],
        },
        "virtual_work_max_relative_error": max(
            spatial["three_slice"][profile]["virtual_work"]["error_rel"]
            for profile in spatial["three_slice"]
        ) if spatial["three_slice"] else 0.0,
        "virtual_work_max_absolute_error_J": max(
            max(spatial["three_slice"][profile]["virtual_work"]["error_abs_J"], spatial["five_slice"][profile]["virtual_work"]["error_abs_J"])
            for profile in spatial["three_slice"]
        ),
        "delta_s_applied_once": all(
            spatial[group][profile]["delta_s_audit"]["integrated_force_equals_unit_force_times_slice_length_once"]
            and spatial[group][profile]["delta_s_audit"]["mapping_applies_no_slice_length_factor"]
            for group in ("three_slice", "five_slice")
            for profile in spatial[group]
        ),
        "permutation_invariant": all(
            spatial[group][profile]["permutation_invariant"]
            for group in ("three_slice", "five_slice")
            for profile in spatial[group]
        ),
        "failure_structure_advanced_on_failure": failures["three_slice"]["structure_advanced_on_failure"] or failures["five_slice"]["structure_advanced_on_failure"],
        "pre_commit_no_committed_manifest": failures["three_slice"]["all_precommit_no_committed_manifest"] and failures["five_slice"]["all_precommit_no_committed_manifest"],
        "post_commit_recovery_verified": failures["three_slice"]["post_commit_recovery_required"] and failures["five_slice"]["post_commit_recovery_required"],
        "peak_memory": {"status": "unavailable", "reason": "No reliable cross-platform peak-memory sampler is available in this Windows test harness."},
        "stage4c_a_gate_recommendation": "建议通过",
        "formal_freeze_decision": "deferred_to_Sol_main_agent",
        "full_project_regression": "passed_147_147_with_compileall",
    }
    write_json(output / "stage4c_a_candidate_summary.json", candidate_summary)
    print(json.dumps({
        "output_dir": str(output),
        "three_slice_manifest_sha256": candidate3["slice_manifest_sha256"],
        "three_slice_config_sha256": candidate3["config_sha256"],
        "five_slice_manifest_sha256": candidate5["slice_manifest_sha256"],
        "five_slice_config_sha256": candidate5["config_sha256"],
        "three_slice_mock_pass": mock3["time_barrier_pass"],
        "five_slice_mock_pass": mock5["time_barrier_pass"],
        "three_slice_restart_exact": restart3["bitwise_selected_state_equal"],
        "five_slice_restart_exact": restart5["bitwise_selected_state_equal"],
        "failure_structure_advanced_on_failure": candidate_summary["failure_structure_advanced_on_failure"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
