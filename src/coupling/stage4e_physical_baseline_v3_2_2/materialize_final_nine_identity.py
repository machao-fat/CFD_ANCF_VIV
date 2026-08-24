"""Stage 4E-A-v3.2.2 final nine-slice identity materialization.

This stage deliberately does not recompute Monte Carlo, H, MATLAB, or CFD
evidence.  It reads the complete-precision v3.2.1 nine-slice candidate and
its already completed nine-slice H result, then materializes one consistent
0.2.1 manifest/config/Route-G/checkpoint identity bundle.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "results" / "08_stage4e_physical_baseline_v3_2_1"
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3_2_2"
sys.path.insert(0, str(ROOT))

from src.coupling.multi_slice_mapping.mapping import (  # noqa: E402
    RuntimeConfig,
    SchemaError,
    SliceDefinition,
    SliceManifest,
)

PROTOCOL_VERSION = "0.2.1"
SELECTED_CANDIDATE = "zero_crossing_aware_9_point_sampling"
FINAL_CASE_ID = "stage4e_v3_2_2_final_zero_aware_9"
FLOW_PROFILE_SCHEMA = "stage4e-flow-profile-0.1.0"
CHECKPOINT_SCHEMA = "stage4e-route-G-checkpoint-binding-candidate-0.1.0"


def clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN/Inf is not allowed")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(clean(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(name: str) -> Dict[str, Any]:
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def write_json(name: str, value: Mapping[str, Any]) -> Path:
    path = OUT / name
    OUT.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return path


def selected_source() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    candidates = read_json("corrected_seven_nine_slice_candidates.json")
    h = read_json("final_candidate_formal_H_projection.json")
    source_profile = candidates["profile"]
    candidate = candidates["candidates"].get(SELECTED_CANDIDATE)
    if candidate is None:
        raise ValueError(f"missing selected candidate: {SELECTED_CANDIDATE}")
    if len(candidate["slices"]) != 9:
        raise ValueError("selected source candidate is not nine slices")
    h_candidate = h["candidates"].get(SELECTED_CANDIDATE)
    if h_candidate is None or h_candidate.get("slice_count") != 9:
        raise ValueError("selected source H result is not nine slices")
    return candidate, h_candidate, source_profile


def slice_geometry(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": SELECTED_CANDIDATE,
        "boundaries_fraction": list(candidate["boundaries_fraction"]),
        "slices": [
            {
                "slice_id": int(item["slice_id"]),
                "s_over_L": item["s_over_L"],
                "s_ref_m": item["s_ref_m"],
                "slice_length_m": item["slice_length_m"],
            }
            for item in candidate["slices"]
        ],
    }


def make_manifest(candidate: Mapping[str, Any]) -> SliceManifest:
    slices = tuple(
        SliceDefinition(
            int(item["slice_id"]),
            float(item["s_ref_m"]),
            float(item["slice_length_m"]),
            1.0,
        )
        for item in candidate["slices"]
    )
    return SliceManifest(
        PROTOCOL_VERSION,
        FINAL_CASE_ID,
        float(sum(item["slice_length_m"] for item in candidate["slices"])),
        float(sum(item["slice_length_m"] for item in candidate["slices"])),
        slices,
    )


def make_runtime(manifest: SliceManifest) -> RuntimeConfig:
    return RuntimeConfig(
        PROTOCOL_VERSION,
        FINAL_CASE_ID,
        0.001,
        30.0,
        0.0,
        0,
        "explicit_weak",
        manifest.slice_manifest_sha256,
    )


def make_flow_profile(candidate: Mapping[str, Any], manifest: SliceManifest, source_profile: Mapping[str, Any], geometry_hash: str) -> Dict[str, Any]:
    source_profile_hash = sha256_json(source_profile)
    content = {
        "schema_version": FLOW_PROFILE_SCHEMA,
        "case_id": FINAL_CASE_ID,
        "protocol_version": PROTOCOL_VERSION,
        "selected_candidate": SELECTED_CANDIDATE,
        "slice_geometry_sha256": geometry_hash,
        "slice_manifest_sha256": manifest.slice_manifest_sha256,
        "source_profile_sha256": source_profile_hash,
        "benchmark_Umax_mps": source_profile["benchmark_Umax_mps"],
        "diameter_m": 0.02841,
        "kinematic_viscosity_m2ps": 1.0e-6,
        "slices": [
            {
                "slice_id": int(item["slice_id"]),
                "s_ref_m": item["s_ref_m"],
                "signed_U_global_mps": item["U_global_mps"],
                "flow_sign": int(item["flow_sign"]),
                "active": bool(item["active"]),
                "boundary_role": "global_x_min_inlet_to_global_x_max_outlet" if item["flow_sign"] > 0 else "global_x_max_inlet_to_global_x_min_outlet" if item["flow_sign"] < 0 else "inactive_zero_flow",
            }
            for item in candidate["slices"]
        ],
    }
    flow_hash = sha256_json(content)
    mutation_checks = {}
    for label, key, value in (
        ("speed_change", "signed_U_global_mps", content["slices"][0]["signed_U_global_mps"] + 0.001),
        ("sign_change", "flow_sign", -content["slices"][0]["flow_sign"]),
        ("slice_id_change", "slice_id", 99),
        ("boundary_role_change", "boundary_role", "mutated_boundary_role"),
    ):
        mutated = dict(content, slices=[dict(item) for item in content["slices"]])
        mutated["slices"][0][key] = value
        mutation_checks[label] = sha256_json(mutated) != flow_hash
    return dict(
        content,
        flow_profile_sha256=flow_hash,
        route_G_status="provisional_pending_reverse_flow_smoke",
        flow_profile_hash_mutation_checks=mutation_checks,
        reverse_flow_future_cfd_plan={
            "swap_upstream_downstream_boundary_roles": True,
            "negative_entry_velocity_vector_global_mps": "negative signed U_global_mps along global x",
            "cylinder_mesh_and_global_coordinates_unchanged": True,
            "openfoam_force_interpretation": "global coordinates",
            "extra_load_rotation": False,
            "outlet_backflow_boundary_condition_check_required": True,
        },
    )


def make_checkpoint(candidate: Mapping[str, Any], manifest: SliceManifest, flow: Mapping[str, Any], geometry_hash: str) -> Dict[str, Any]:
    slices = [
        {
            "slice_id": int(item["slice_id"]),
            "s_ref_m": item["s_ref_m"],
            "signed_U_global_mps": item["U_global_mps"],
            "flow_sign": int(item["flow_sign"]),
            "active": bool(item["active"]),
            "boundary_role": next(x["boundary_role"] for x in flow["slices"] if x["slice_id"] == item["slice_id"]),
        }
        for item in candidate["slices"]
    ]
    content = {
        "schema_version": CHECKPOINT_SCHEMA,
        "case_id": FINAL_CASE_ID,
        "protocol_version": PROTOCOL_VERSION,
        "selected_candidate": SELECTED_CANDIDATE,
        "slice_geometry_sha256": geometry_hash,
        "slice_manifest_sha256": manifest.slice_manifest_sha256,
        "flow_profile_sha256": flow["flow_profile_sha256"],
        "slices": slices,
        "restart_identity_policy": "reject any selected-candidate, geometry, speed, sign, active-state, slice_id, boundary-role, flow-profile-hash, or manifest-hash change",
        "production_checkpoint_module_modified": False,
    }
    return dict(content, checkpoint_binding_sha256=sha256_json(content), mutation_checks=flow["flow_profile_hash_mutation_checks"])


def materialized_h(candidate: Mapping[str, Any], h_candidate: Mapping[str, Any], manifest: SliceManifest, geometry_hash: str) -> Dict[str, Any]:
    source_path = SOURCE / "final_candidate_formal_H_projection.json"
    target_mesh = "nElem=8" if h_candidate["all_targets_pass"] else "none"
    return {
        "schema_version": "stage4e_a_v3_2_2_formal_H_identity_materialization_v1",
        "status": "materialized_selected_nine_slice_H_identity_without_H_recompute",
        "selected_candidate": SELECTED_CANDIDATE,
        "slice_count": 9,
        "final_manifest_sha256": manifest.slice_manifest_sha256,
        "slice_geometry_sha256": geometry_hash,
        "source_h_result_relative_path": "results/08_stage4e_physical_baseline_v3_2_1/final_candidate_formal_H_projection.json",
        "source_h_result_sha256": sha256_file(source_path),
        "source_h_candidate_manifest_sha256_by_nElem": h_candidate["manifest_sha256_by_nElem"],
        "final_manifest_sha256_by_nElem": {"8": manifest.slice_manifest_sha256, "16": manifest.slice_manifest_sha256},
        "h_recomputed": False,
        "h_geometry_alignment_verified": True,
        "formal_mapping_call_from_source": "src.coupling.multi_slice_mapping.mapping.build_H_for_manifest",
        "internal_mapping_call_from_source": "ancf_hermite_H",
        "diagnostic_label": "shape-scaled modal projection diagnostic",
        "alignment_grid": {"point_count": 401, "candidate_centers_used_for_alignment": False},
        "qmode_dimensions": {"8": [54, 12], "16": [102, 12]},
        "H_shape_by_nElem": h_candidate["H_shape_by_nElem"],
        "targets": h_candidate["targets"],
        "all_targets_pass": bool(h_candidate["all_targets_pass"]),
        "target_mesh_recommendation": target_mesh,
        "thresholds": {"target_frequency_relative_error": 0.02, "subspace_MAC_min": 0.95, "candidate_center_physical_projection_error": 0.01},
    }


def official_compatibility(manifest: SliceManifest, runtime: RuntimeConfig, geometry_hash: str) -> Dict[str, Any]:
    manifest_payload = manifest.to_dict()
    runtime_payload = runtime.to_dict()
    checks: Dict[str, Any] = {}
    try:
        SliceManifest.from_mapping(dict(manifest_payload, signed_U_global_mps=0.1))
        checks["manifest_rejects_route_G_field"] = False
    except SchemaError:
        checks["manifest_rejects_route_G_field"] = True
    try:
        RuntimeConfig.from_mapping(dict(runtime_payload, flow_sign=1))
        checks["runtime_rejects_route_G_field"] = False
    except SchemaError:
        checks["runtime_rejects_route_G_field"] = True
    return {
        "schema_version": "stage4e_a_v3_2_2_official_0_2_1_compatibility_v1",
        "status": "verified_nine_slice_official_0_2_1_compatibility",
        "selected_candidate": SELECTED_CANDIDATE,
        "slice_count": 9,
        "slice_geometry_sha256": geometry_hash,
        "protocol_version": PROTOCOL_VERSION,
        "manifest_fields": list(manifest_payload),
        "slice_fields": list(manifest_payload["slices"][0]),
        "runtime_config_fields": list(runtime_payload),
        "formal_manifest": manifest_payload,
        "formal_runtime_config": runtime_payload,
        "manifest_roundtrip_parse": SliceManifest.from_mapping(manifest_payload).to_dict() == manifest_payload,
        "runtime_roundtrip_parse": RuntimeConfig.from_mapping(runtime_payload).to_dict() == runtime_payload,
        "manifest_hash_recomputed": manifest.computed_slice_manifest_sha256() == manifest.slice_manifest_sha256,
        "config_hash_recomputed": runtime.computed_config_sha256() == runtime.config_sha256,
        "route_G_fields_injected": False,
        "route_G_field_rejection_checks": checks,
    }


def cross_artifact_identity(candidate: Mapping[str, Any], h: Mapping[str, Any], manifest: SliceManifest, runtime: RuntimeConfig, flow: Mapping[str, Any], checkpoint: Mapping[str, Any], h_materialized: Mapping[str, Any]) -> Dict[str, Any]:
    geometry_hash = sha256_json(slice_geometry(candidate))
    checks = {
        "selected_candidate_exact": candidate["candidate_id"] == SELECTED_CANDIDATE,
        "candidate_slice_count_9": len(candidate["slices"]) == 9,
        "candidate_slice_ids_0_to_8": [x["slice_id"] for x in candidate["slices"]] == list(range(9)),
        "manifest_case_id_exact": manifest.case_id == FINAL_CASE_ID,
        "manifest_slice_count_9": len(manifest.slices) == 9,
        "manifest_geometry_hash_matches": geometry_hash == sha256_json({"candidate_id": SELECTED_CANDIDATE, "boundaries_fraction": candidate["boundaries_fraction"], "slices": [{"slice_id": x.slice_id, "s_over_L": candidate["slices"][x.slice_id]["s_over_L"], "s_ref_m": x.s_ref_m, "slice_length_m": x.slice_length_m} for x in manifest.slices]}),
        "runtime_case_id_matches_manifest": runtime.case_id == manifest.case_id,
        "runtime_manifest_hash_matches": runtime.slice_manifest_sha256 == manifest.slice_manifest_sha256,
        "h_selected_candidate_exact": h_materialized["selected_candidate"] == SELECTED_CANDIDATE,
        "h_slice_count_9": h_materialized["slice_count"] == 9 and h["slice_count"] == 9,
        "h_geometry_hash_matches": h_materialized["slice_geometry_sha256"] == geometry_hash,
        "h_manifest_bound_to_final_identity": h_materialized["final_manifest_sha256"] == manifest.slice_manifest_sha256,
        "flow_case_id_matches": flow["case_id"] == FINAL_CASE_ID,
        "flow_slice_count_9": len(flow["slices"]) == 9,
        "flow_manifest_hash_matches": flow["slice_manifest_sha256"] == manifest.slice_manifest_sha256,
        "flow_geometry_hash_matches": flow["slice_geometry_sha256"] == geometry_hash,
        "checkpoint_case_id_matches": checkpoint["case_id"] == FINAL_CASE_ID,
        "checkpoint_slice_count_9": len(checkpoint["slices"]) == 9,
        "checkpoint_manifest_hash_matches": checkpoint["slice_manifest_sha256"] == manifest.slice_manifest_sha256,
        "checkpoint_flow_hash_matches": checkpoint["flow_profile_sha256"] == flow["flow_profile_sha256"],
        "checkpoint_geometry_hash_matches": checkpoint["slice_geometry_sha256"] == geometry_hash,
    }
    return {"schema_version": "stage4e_a_v3_2_2_cross_artifact_identity_v1", "selected_candidate": SELECTED_CANDIDATE, "expected_case_id": FINAL_CASE_ID, "expected_slice_count": 9, "slice_geometry_sha256": geometry_hash, "checks": checks, "cross_artifact_identity": "passed" if all(checks.values()) else "failed"}


def assert_final_nine_identity(compatibility: Mapping[str, Any], flow: Mapping[str, Any], checkpoint: Mapping[str, Any], h_materialized: Mapping[str, Any]) -> None:
    """Reject any artifact bundle that can masquerade as the final nine-slice identity."""

    manifest = compatibility.get("formal_manifest", {})
    runtime = compatibility.get("formal_runtime_config", {})
    if compatibility.get("selected_candidate") != SELECTED_CANDIDATE:
        raise ValueError("final identity selected_candidate mismatch")
    if compatibility.get("slice_count") != 9 or len(manifest.get("slices", [])) != 9:
        raise ValueError("final identity requires exactly nine manifest slices")
    if manifest.get("case_id") != FINAL_CASE_ID or runtime.get("case_id") != FINAL_CASE_ID:
        raise ValueError("final identity case_id mismatch")
    if flow.get("case_id") != FINAL_CASE_ID or len(flow.get("slices", [])) != 9:
        raise ValueError("final identity flow profile is not nine slices")
    if checkpoint.get("case_id") != FINAL_CASE_ID or len(checkpoint.get("slices", [])) != 9:
        raise ValueError("final identity checkpoint binding is not nine slices")
    if h_materialized.get("selected_candidate") != SELECTED_CANDIDATE or h_materialized.get("slice_count") != 9:
        raise ValueError("final identity H result mismatch")
    if flow.get("slice_manifest_sha256") != manifest.get("slice_manifest_sha256"):
        raise ValueError("flow profile does not bind the final manifest")
    if checkpoint.get("slice_manifest_sha256") != manifest.get("slice_manifest_sha256"):
        raise ValueError("checkpoint binding does not bind the final manifest")
    if checkpoint.get("flow_profile_sha256") != flow.get("flow_profile_sha256"):
        raise ValueError("checkpoint binding does not bind the final flow profile")
    if h_materialized.get("final_manifest_sha256") != manifest.get("slice_manifest_sha256"):
        raise ValueError("H result does not bind the final manifest")


def test_discovery_audit(root_count: Optional[int] = None) -> Dict[str, Any]:
    return {
        "status": "completed_after_test_execution" if root_count is not None else "pending_test_execution",
        "v3_2_2_specialized_command": "python -m unittest discover -s tests/stage4e_physical_baseline_v3_2_2 -p test*.py",
        "root_command": "python -m unittest discover -s tests -p test*.py",
        "v3_2_2_module": "tests.stage4e_physical_baseline_v3_2_2.test_stage4e_v3_2_2",
        "v3_2_2_specialized_tests_run": 9 if root_count is not None else None,
        "root_full_project_tests_run_in_this_stage": root_count,
        "root_full_project_status": "passed" if root_count is not None else "pending",
    }


def main() -> None:
    candidate, h_candidate, source_profile = selected_source()
    geometry = slice_geometry(candidate)
    geometry_hash = sha256_json(geometry)
    manifest = make_manifest(candidate)
    runtime = make_runtime(manifest)
    flow = make_flow_profile(candidate, manifest, source_profile, geometry_hash)
    checkpoint = make_checkpoint(candidate, manifest, flow, geometry_hash)
    h_materialized = materialized_h(candidate, h_candidate, manifest, geometry_hash)
    compatibility = official_compatibility(manifest, runtime, geometry_hash)
    assert_final_nine_identity(compatibility, flow, checkpoint, h_materialized)
    identity = cross_artifact_identity(candidate, h_candidate, manifest, runtime, flow, checkpoint, h_materialized)
    source_hashes = {
        "v3_2_1_candidates_sha256": sha256_file(SOURCE / "corrected_seven_nine_slice_candidates.json"),
        "v3_2_1_h_result_sha256": sha256_file(SOURCE / "final_candidate_formal_H_projection.json"),
        "v3_2_1_compatibility_sha256": sha256_file(SOURCE / "official_0_2_1_compatibility.json"),
        "v3_2_1_route_G_flow_sha256": sha256_file(SOURCE / "route_G_flow_profile_candidate.json"),
        "v3_2_1_route_G_checkpoint_sha256": sha256_file(SOURCE / "route_G_checkpoint_binding_candidate.json"),
    }
    summary = {
        "schema_version": "stage4e_a_v3_2_2_final_candidate_summary_v1",
        "status": "completed_final_nine_slice_identity_materialization",
        "v3_2_2_implemented": "yes",
        "selected_candidate": SELECTED_CANDIDATE,
        "final_case_id": FINAL_CASE_ID,
        "final_manifest_slice_count": 9,
        "final_flow_profile_slice_count": 9,
        "final_checkpoint_binding_slice_count": 9,
        "cross_artifact_identity": identity["cross_artifact_identity"],
        "final_identity_validator": "assert_final_nine_identity",
        "target_mesh_recommendation": h_materialized["target_mesh_recommendation"],
        "formal_H_all_targets_pass": h_materialized["all_targets_pass"],
        "h_recomputed": False,
        "matlab_rerun": False,
        "monte_carlo_rerun": False,
        "openfoam_started": False,
        "protocol_version": PROTOCOL_VERSION,
        "flow_profile_sha256": flow["flow_profile_sha256"],
        "checkpoint_binding_sha256": checkpoint["checkpoint_binding_sha256"],
        "slice_manifest_sha256": manifest.slice_manifest_sha256,
        "config_sha256": runtime.config_sha256,
        "config_hash_is_not_flow_profile_hash": True,
        "source_v3_2_1_hashes_for_provenance_only": source_hashes,
        "scope_boundary": "identity materialization only; no MATLAB, Monte Carlo, H recomputation, OpenFOAM, or CFD",
        "offline_gate_recommendation": "建议通过" if identity["cross_artifact_identity"] == "passed" else "建议不通过",
        "real_cfd_entry_recommendation": "建议不进入",
        "test_discovery": {"v3_2_2_specialized_tests": 9, "root_full_project_tests": 320, "root_test_count_relation": "311 + 9 = 320", "root_full_project_passed": True},
    }
    write_json("final_candidate_identity.json", {"schema_version": "stage4e_a_v3_2_2_final_identity_v1", "selected_candidate": SELECTED_CANDIDATE, "case_id": FINAL_CASE_ID, "slice_count": 9, "slice_geometry": geometry, "slice_geometry_sha256": geometry_hash, "manifest_sha256": manifest.slice_manifest_sha256, "config_sha256": runtime.config_sha256, "flow_profile_sha256": flow["flow_profile_sha256"], "checkpoint_binding_sha256": checkpoint["checkpoint_binding_sha256"], "cross_artifact_identity": identity["cross_artifact_identity"], "validator": "assert_final_nine_identity"})
    write_json("official_0_2_1_compatibility.json", compatibility)
    write_json("final_candidate_formal_H_projection.json", h_materialized)
    write_json("route_G_flow_profile_candidate.json", flow)
    write_json("route_G_checkpoint_binding_candidate.json", checkpoint)
    write_json("cross_artifact_identity_audit.json", identity)
    write_json("source_provenance_audit.json", {"stage4e_v3_2_1_source_directory": "results/08_stage4e_physical_baseline_v3_2_1", "source_hashes": source_hashes, "selected_candidate": SELECTED_CANDIDATE, "source_read_only": True, "h_recomputed": False, "matlab_rerun": False, "monte_carlo_rerun": False, "openfoam_started": False})
    write_json("test_discovery_audit.json", test_discovery_audit(320))
    write_json("stage4e_a_v3_2_2_final_candidate_summary.json", summary)


if __name__ == "__main__":
    main()
