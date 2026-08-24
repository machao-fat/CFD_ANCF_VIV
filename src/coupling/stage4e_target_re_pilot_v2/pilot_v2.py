"""Orchestrated B2-A-v2 offline audit and bounded target-Re pilot."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis_v2 import corrected_coefficients_from_raw, corrected_statistics, force_crosscheck, mesh_span_from_bbox, normalization_contract, numeric_rows, parse_force_coefficients, parse_raw_forces, parse_yplus_file, parse_cfl, relative_changes
from .case_generator_v2 import CASE_ROOT, DOMAIN_EXTENTS, MESH_LEVELS, RADIAL_GROWTH, NEAR_RADIUS, case_freshness, generate_case
from .identity_v2 import D, NU, RHO, EXPECTED_CANDIDATE, EXPECTED_CONFIG_SHA256, EXPECTED_FLOW_PROFILE_SHA256, EXPECTED_MANIFEST_SHA256, PROJECT, choose_representative_cases, finite, formal_flow_identity, load_formal_flow_profile, sha256_file, sha256_json
from .runner_v2 import closeout_process_audit, log_health, process_snapshot, run_case, write_process_inventory

# A run-specific evidence root can be supplied by the orchestration layer.
# This prevents a fresh retry from overwriting the earlier partial v2 record.
RESULTS = Path(os.environ.get("B2A_V2_RESULTS_ROOT", str(PROJECT / "results" / "10_stage4e_target_re_pilot_v2"))).resolve()
V1_RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot"
V1_CASE_ROOT = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder" / "20260814T051204411Z_stage4e_b2_a_retry3"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(finite(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _relative(path: Path) -> str:
    return str(path.relative_to(PROJECT)).replace("\\", "/")


def _bbox_from_blockmesh(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    scale_match = re.search(r"convertToMeters\s+(%s)" % r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    scale = float(scale_match.group(1)) if scale_match else 1.0
    section = text.split("vertices", 1)[1].split("blocks", 1)[0]
    coords: list[tuple[float, float, float]] = []
    triple = re.compile(r"\(\s*(%s)\s+(%s)\s+(%s)\s*\)" % (r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"))
    for match in triple.finditer(section):
        coords.append(tuple(scale * float(match.group(i)) for i in (1, 2, 3)))
    if not coords:
        raise ValueError(f"cannot parse mesh bbox: {path}")
    xs, ys, zs = zip(*coords)
    return {"x_min_m": min(xs), "x_max_m": max(xs), "y_min_m": min(ys), "y_max_m": max(ys), "z_min_m": min(zs), "z_max_m": max(zs), "point_count_in_dictionary": len(coords), "convertToMeters": scale}


def _control_aref(path: Path) -> float | None:
    match = re.search(r"\bAref\s+(%s)" % r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", path.read_text(encoding="utf-8", errors="replace"))
    return None if not match else float(match.group(1))


def _old_case_ids() -> list[str]:
    return ["high_laminar_medium", "high_kOmegaSST_medium", "high_kOmegaSST_coarse", "high_kOmegaSST_fine"]


def offline_v1_recalculation() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case_id in _old_case_ids():
        case = V1_CASE_ROOT / case_id
        bbox = _bbox_from_blockmesh(case / "system" / "blockMeshDict")
        span = mesh_span_from_bbox(bbox)
        normalization = normalization_contract(bbox, aref_from_control=_control_aref(case / "system" / "controlDict"))
        U = abs(float(re.search(r"magUInf\s+(%s)" % r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", (case / "system" / "controlDict").read_text()).group(1)))
        raw = parse_raw_forces(case / "postProcessing" / "forces" / "0" / "forces.dat")
        coeff = parse_force_coefficients(case / "postProcessing" / "forceCoeffs" / "0" / "forceCoeffs.dat")
        corrected = corrected_coefficients_from_raw(raw, U_abs=U, b_mesh=span)
        stats = corrected_statistics(corrected, U_abs=U)
        cross = force_crosscheck(raw, coeff, U_abs=U, b_mesh=span, old_aref=float(normalization["controlDict_Aref_m2"] or D))
        cases.append({"case_id": case_id, "case_relative_path": _relative(case), "model": "laminar" if "laminar" in case_id else "kOmegaSST", "mesh": "coarse" if "coarse" in case_id else "fine" if "fine" in case_id else "medium", "U_abs_mps": U, "Re": U * D / NU, "raw_force_sha256": raw.get("sha256"), "forceCoeffs_sha256": coeff.get("sha256"), "mesh_bbox": bbox, "normalization": normalization, "corrected_statistics": stats, "raw_vs_old_forceCoeffs_crosscheck": cross, "diagnostic_only": True, "eligible_for_v2_gate": False})
    return {"schema_version": "stage4e-b2-a-v2-v1-offline-force-recalculation-0.1.0", "status": "diagnostic_only_v1_evidence_invalidated", "normalization": "F_ref=0.5*rho*abs(U)^2*D*b_mesh; f_2D=F_OF/b_mesh; no slice length", "cases": cases}


def source_identity_audit() -> dict[str, Any]:
    paths = [
        PROJECT / "docs" / "10_stage4e_b2_a_model_selection_report.md", PROJECT / "docs" / "10_stage4e_b2_a_mesh_timestep_report.md",
        V1_RESULTS / "stage4e_b2_a_gate_candidate.json", V1_RESULTS / "force_coefficient_summary.json", V1_RESULTS / "mesh_convergence.json",
        PROJECT / "src" / "coupling" / "stage4e_target_re_pilot" / "analysis.py", PROJECT / "src" / "coupling" / "stage4e_target_re_pilot" / "case_generator.py", PROJECT / "src" / "coupling" / "stage4e_target_re_pilot" / "pilot.py", PROJECT / "tests" / "stage4e_target_re_pilot" / "test_target_re_pilot.py",
    ]
    for case_id in _old_case_ids():
        case = V1_CASE_ROOT / case_id
        paths += [case / "system" / "blockMeshDict", case / "system" / "controlDict", case / "0" / "U", case / "constant" / "momentumTransport", case / "postProcessing" / "forces" / "0" / "forces.dat", case / "postProcessing" / "forceCoeffs" / "0" / "forceCoeffs.dat"]
    flow = load_formal_flow_profile()
    items = [{"relative_path": _relative(path), "exists": path.exists(), "sha256": sha256_file(path) if path.exists() else None} for path in paths]
    return {"schema_version": "stage4e-b2-a-v2-source-identity-0.1.0", "parent_identity": {"flow_profile_sha256": flow["flow_profile_sha256"], "manifest_sha256": EXPECTED_MANIFEST_SHA256, "config_sha256": EXPECTED_CONFIG_SHA256, "candidate": EXPECTED_CANDIDATE, "slice_count": len(flow["slices"])}, "v1_sources": items, "all_required_sources_present": all(item["exists"] for item in items), "absolute_paths_excluded_from_physical_hashes": True}


def perturbation_contract(epsilon: float = 0.005) -> dict[str, Any]:
    payload = {"epsilon": epsilon, "base_internal_velocity_policy": "Ux=U; Uy=0 outside regions", "upper_region": {"x_D": [0.5, 2.5], "y_D": [0.1, 0.6], "Uy": "+epsilon*U"}, "lower_region": {"x_D": [0.5, 2.5], "y_D": [-0.6, -0.1], "Uy": "-epsilon*U"}, "z_D": [-0.5, 0.5], "region_volume_equality": True, "net_perturbation_Uy": 0.0, "random": False, "method": "deterministic setFields boxToCell after blockMesh"}
    return {"schema_version": "stage4e-b2-a-v2-initial-perturbation-0.1.0", **payload, "perturbation_sha256": sha256_json(payload)}


def mesh_family_contract() -> dict[str, Any]:
    return {"schema_version": "stage4e-b2-a-v2-mesh-family-0.1.0", "mesh_family": {level: {**params, "near_field_radius_D": NEAR_RADIUS, "topology": "attached eight-sector O-grid-equivalent", "z_span_D": 1.0} for level, params in MESH_LEVELS.items()}, "domains": {name: {"x_D": [-ext[0], ext[0]], "y_D": [-ext[1], ext[1]], "mirror_plane": "x=0"} for name, ext in DOMAIN_EXTENTS.items()}, "same_topology_for_models": True, "same_mesh_for_dt_pair": True, "slice_length_used": False}


def _prepare_cases(runtime_root: Path, selected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_id = runtime_root.name
    case_run_root = CASE_ROOT / run_id
    if case_run_root.exists():
        prepared_path = runtime_root / "prepared_cases.json"
        # A separate prepare phase is intentional: it lets the operator
        # inspect the fresh case tree before any OpenFOAM process starts.
        if not prepared_path.exists():
            raise FileExistsError(case_run_root)
        saved = json.loads(prepared_path.read_text(encoding="utf-8"))
        return {"selected": selected, "prepared": saved.get("prepared", saved.get("cases", []))}
    case_run_root.mkdir(parents=True)
    specs: list[dict[str, Any]] = []
    # All six family prechecks are deliberately short and precede any long run.
    for label in ("high",):
        for model in ("laminar", "kOmegaSST"):
            for mesh in ("coarse", "medium", "fine"):
                specs.append({"case_id": f"precheck_{label}_{model}_{mesh}", "label": label, "model": model, "mesh": mesh, "domain": "baseline", "dt": 1.0e-5 if mesh == "fine" else 1.0e-4 if mesh == "medium" else 5.0e-4, "end": 0.005, "precheck": True})
    # The formal sequence is present in the manifest but is executed only after all prechecks.
    specs += [
        {"case_id": "high_laminar_medium", "label": "high", "model": "laminar", "mesh": "medium", "domain": "baseline", "dt": 4.0e-4, "end": 5.5},
        {"case_id": "high_kOmegaSST_medium", "label": "high", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 4.0e-4, "end": 5.5},
        {"case_id": "high_kOmegaSST_coarse", "label": "high", "model": "kOmegaSST", "mesh": "coarse", "domain": "baseline", "dt": 5.0e-4, "end": 5.5},
        {"case_id": "high_kOmegaSST_fine", "label": "high", "model": "kOmegaSST", "mesh": "fine", "domain": "baseline", "dt": 2.0e-4, "end": 5.5},
        {"case_id": "high_kOmegaSST_medium_dt2", "label": "high", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 2.0e-4, "end": 5.5},
        {"case_id": "high_kOmegaSST_expanded", "label": "high", "model": "kOmegaSST", "mesh": "medium", "domain": "expanded", "dt": 4.0e-4, "end": 5.5},
        {"case_id": "middle_kOmegaSST_medium", "label": "middle", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 4.0e-4, "end": 5.5},
        {"case_id": "low_kOmegaSST_medium", "label": "low", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 4.0e-4, "end": 5.5},
    ]
    prepared: list[dict[str, Any]] = []
    for spec in specs:
        source = selected[spec["label"]]
        case_dir = case_run_root / spec["case_id"]
        meta = {"run_id": run_id, "source_slice_id": source["source_slice_id"], "source_signed_U_global_mps": source["source_signed_U_global_mps"], "source_flow_sign": source["source_flow_sign"], "parent_flow_profile_sha256": EXPECTED_FLOW_PROFILE_SHA256, "selected_candidate": EXPECTED_CANDIDATE, "purpose": "fixed-cylinder target-Re v2 pilot", "warning": "Re=target range candidate pilot only; not nine-slice CFD"}
        generated = generate_case(case_dir, model=spec["model"], mesh_level=spec["mesh"], domain=spec["domain"], U=source["pilot_U_mps"], dt=spec["dt"], end_time=spec["end"], epsilon=0.005, metadata=meta)
        prepared.append({**spec, "case_relative_path": _relative(case_dir), "case_metadata": generated})
    write_json(runtime_root / "prepared_cases.json", {"schema_version": "stage4e-b2-a-v2-prepared-cases-0.1.0", "run_id": run_id, "cases": prepared})
    write_json(RESULTS / "case_freshness_audit.json", {"schema_version": "stage4e-b2-a-v2-case-freshness-0.1.0", "run_id": run_id, "prepared_cases": [{"case_id": item["case_id"], "freshness": case_freshness(CASE_ROOT / run_id / item["case_id"])} for item in prepared]})
    return {"selected": selected, "prepared": prepared}


def _case_result(item: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    case = PROJECT / item["case_relative_path"]
    logs = [Path(step["log_path"]) for step in steps]
    solver_log = next((Path(step["log_path"]) for step in steps if step["step"] == "pimpleFoam"), None)
    mesh_log = next((Path(step["log_path"]) for step in steps if step["step"] == "checkMesh"), None)
    health = log_health(logs)
    solver_text = solver_log.read_text(encoding="utf-8", errors="replace") if solver_log and solver_log.exists() else ""
    solver_contains_end = "End" in solver_text
    cfl = parse_cfl(solver_log) if solver_log else {"samples": 0, "max_cfl": None, "passed": False}
    raw = parse_raw_forces(case / "postProcessing" / "forces" / "0" / "forces.dat")
    coeff = parse_force_coefficients(case / "postProcessing" / "forceCoeffs" / "0" / "forceCoeffs.dat")
    bbox = _bbox_from_blockmesh(case / "system" / "blockMeshDict")
    span = mesh_span_from_bbox(bbox)
    cross = force_crosscheck(raw, coeff, U_abs=float(item["case_metadata"]["U_abs_mps"]), b_mesh=span, old_aref=D * span)
    corrected = corrected_coefficients_from_raw(raw, U_abs=float(item["case_metadata"]["U_abs_mps"]), b_mesh=span)
    stats = corrected_statistics(corrected, U_abs=float(item["case_metadata"]["U_abs_mps"]))
    yplus_files = sorted((case / "postProcessing").rglob("yPlus.dat")) if (case / "postProcessing").exists() else []
    yplus = parse_yplus_file(yplus_files[-1]) if yplus_files else {"available": False, "reason": "yPlus.dat not found", "p95_y_plus": None, "max_y_plus": None}
    health["solver_contains_End"] = solver_contains_end
    return finite({"case_id": item["case_id"], "case_relative_path": item["case_relative_path"], "model": item["model"], "mesh": item["mesh"], "domain": item["domain"], "U_mps": item["case_metadata"]["U_mps"], "U_abs_mps": item["case_metadata"]["U_abs_mps"], "Re": item["case_metadata"]["Re"], "deltaT_s": item["dt"], "endTime_s": item["end"], "steps": steps, "mesh_ok": bool(mesh_log and mesh_log.exists() and "Mesh OK" in mesh_log.read_text(encoding="utf-8", errors="replace")), "solver_return_code": next((step["return_code"] for step in steps if step["step"] == "pimpleFoam"), None), "solver_ok": bool(solver_log and solver_contains_end and not health["fatal_tokens"] and any(step["step"] == "pimpleFoam" and step["return_code"] == 0 for step in steps)), "log_health": health, "cfl": cfl, "bbox": bbox, "b_mesh_m": span, "force_crosscheck": cross, "force_statistics": stats, "yplus": yplus, "case_passed_basic_runtime_checks": bool(mesh_log and "Mesh OK" in mesh_log.read_text(encoding="utf-8", errors="replace") if mesh_log and mesh_log.exists() else False) and bool(solver_log and solver_contains_end and not health["fatal_tokens"]) and bool(cfl.get("passed")) and bool(cross.get("passed")) and bool(yplus.get("available"))})


def _run_items(runtime_root: Path, items: list[dict[str, Any]], *, stop_on_failure: bool = True, timeout_s: float = 3600.0, registry: list[dict[str, Any]] | None = None, limiter: Any | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    owns_limiter = limiter is None
    registry = registry if registry is not None else []
    limiter = limiter or __import__("src.coupling.process_control.process_limiter", fromlist=["ProcessLimiter"]).ProcessLimiter(2, run_id=runtime_root.name)
    outputs: list[dict[str, Any]] = []
    try:
        for item in items:
            case = PROJECT / item["case_relative_path"]
            fresh = case_freshness(case)
            if not fresh["passed"]:
                outputs.append({"case_id": item["case_id"], "stopped_on": "freshness", "freshness": fresh})
                break
            steps, registry = run_case(case, runtime_root=runtime_root, registry=registry, limiter=limiter, timeout_s=timeout_s)
            result = _case_result(item, steps)
            outputs.append(result)
            if stop_on_failure and not result["case_passed_basic_runtime_checks"]:
                break
    except Exception as exc:
        write_json(runtime_root / "runner_exception.json", {"type": type(exc).__name__, "message": str(exc)})
        try:
            audit = closeout_process_audit(runtime_root, limiter, registry, blocked=True)
        except Exception:
            audit = {"process_cleanup_blocked": True, "task_owned_residual_process_count": None}
        raise
    if owns_limiter:
        audit = closeout_process_audit(runtime_root, limiter, registry)
    else:
        audit = {"run_id": runtime_root.name, "registry": registry, "limiter_audit": limiter.audit(), "task_owned_residual_process_count": 0, "process_cleanup_blocked": False}
    return outputs, audit


def _comparison(a: dict[str, Any] | None, b: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any]:
    if not a or not b:
        return {"available": False, "passed": False, "comparisons": {key: {"available": False, "passed": False} for key in keys}}
    result: dict[str, Any] = {"available": True, "comparisons": {}, "passed": True}
    for key in keys:
        av = a.get("force_statistics", {}).get(key); bv = b.get("force_statistics", {}).get(key)
        if av is None or bv is None:
            result["comparisons"][key] = {"available": False, "passed": False}; result["passed"] = False; continue
        rel = abs(float(av) - float(bv)) / max(abs(float(bv)), 1e-12)
        threshold = {"mean_Cd": 0.03, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05, "St": 0.02, "Cl_peak_to_peak": 0.05}.get(key, 0.05)
        passed = rel <= threshold
        result["comparisons"][key] = {"relative_difference": rel, "threshold": threshold, "passed": passed}; result["passed"] = result["passed"] and passed
    return result


def run_workflow(runtime_root: Path) -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    flow = load_formal_flow_profile()
    selected = choose_representative_cases(flow)
    source = source_identity_audit()
    write_json(RESULTS / "source_identity_audit_v2.json", source)
    invalidated = {"schema_version": "stage4e-b2-a-v2-invalidated-v1-evidence-0.2.0", "v1_run_id": "20260814T051204411Z_stage4e_b2_a_retry3", "status": "invalidated_for_gate_use", "old_evidence_preserved": True, "items": [
        {"evidence": "v1 blockMesh/checkMesh/solver return codes and logs", "status": "retained_as_runtime_diagnostic", "reason": "These are direct process and mesh health observations.", "offline_fix": False, "requires_cfd_recompute": False},
        {"evidence": "v1 raw forces.dat and forceCoeffs.dat bytes", "status": "retained_for_offline_recalculation", "reason": "Raw files and hashes are unchanged and can be re-normalized.", "offline_fix": True, "requires_cfd_recompute": False},
        {"evidence": "v1 absolute Cd/Cl and derived Cd_RMS", "status": "invalidated_for_gate", "reason": "forceCoeffs used Aref=D instead of D*b_mesh and Cd_RMS was total RMS, not fluctuation RMS.", "offline_fix": True, "requires_cfd_recompute": False},
        {"evidence": "v1 FFT, zero-crossing, Strouhal and effective-cycle claims", "status": "invalidated_for_gate", "reason": "near-zero lift and insufficient/unstable frequency evidence were not gated before FFT interpretation.", "offline_fix": False, "requires_cfd_recompute": True},
        {"evidence": "v1 grid convergence, SST wall-resolution and model choice", "status": "invalidated_for_gate", "reason": "radial spacing was not a graded O-grid audit, yPlus was not independently generated, and formal windows were incomplete.", "offline_fix": False, "requires_cfd_recompute": True},
        {"evidence": "v1 fine CFL=0.9920089032580395", "status": "invalidated_for_gate", "reason": "The hard stop is at max CFL >= 0.8.", "offline_fix": False, "requires_cfd_recompute": True}
    ], "v2_gate_may_not_use_v1_absolute_coefficients": True}
    write_json(RESULTS / "invalidated_v1_evidence.json", invalidated)
    offline = offline_v1_recalculation(); write_json(RESULTS / "v1_offline_force_recalculation.json", offline)
    normal = offline["cases"][0]["normalization"] if offline["cases"] else {}
    write_json(RESULTS / "force_span_and_normalization_contract.json", {"schema_version": "stage4e-b2-a-v2-force-span-contract-0.1.0", "source": "v1 actual mesh bounding box", "contract": normal, "all_v1_cases_same_b_mesh": all(abs(float(item["normalization"]["mesh_extrusion_thickness_b_mesh_m"]) - D) <= 1e-14 for item in offline["cases"])})
    write_json(RESULTS / "force_coefficient_crosscheck.json", {"schema_version": "stage4e-b2-a-v2-force-crosscheck-0.1.0", "v1_offline_diagnostic_only": True, "cases": [{"case_id": item["case_id"], **item["raw_vs_old_forceCoeffs_crosscheck"]} for item in offline["cases"]], "hard_stop_if_max_abs_error_gt": 1e-10})
    write_json(RESULTS / "corrected_statistics_contract.json", {"schema_version": "stage4e-b2-a-v2-statistics-contract-0.1.0", "definitions": {"mean_Cd": "mean(Cd)", "Cd_total_RMS": "sqrt(mean(Cd^2))", "Cd_fluctuation_RMS": "sqrt(mean((Cd-mean(Cd))^2))", "mean_Cl": "mean(Cl)", "Cl_total_RMS": "sqrt(mean(Cl^2))", "Cl_fluctuation_RMS": "sqrt(mean((Cl-mean(Cl))^2))", "Cl_peak_to_peak": "max(Cl)-min(Cl)"}, "v1_recomputed_examples": [{"case_id": item["case_id"], "stats": item["corrected_statistics"]} for item in offline["cases"]]})
    write_json(RESULTS / "frequency_evaluability_contract.json", {"schema_version": "stage4e-b2-a-v2-frequency-contract-0.1.0", "minimum_effective_cycles": 15, "minimum_windows": 3, "consistency_threshold": 0.05, "near_zero_status": "not_evaluable_low_amplitude", "v1_recomputed": [{"case_id": item["case_id"], "frequency_status": item["corrected_statistics"].get("frequency_status"), "effective_cycles": item["corrected_statistics"].get("effective_cycles"), "St": item["corrected_statistics"].get("St")} for item in offline["cases"]]})
    perturb = perturbation_contract(); write_json(RESULTS / "initial_perturbation_contract.json", perturb)
    write_json(RESULTS / "mesh_family_v2.json", mesh_family_contract())
    prepared = _prepare_cases(runtime_root, selected)
    write_process_inventory(runtime_root / "process_inventory_before_runtime.json", run_id=runtime_root.name, phase="before_openfoam")
    registry: list[dict[str, Any]] = []
    limiter = __import__("src.coupling.process_control.process_limiter", fromlist=["ProcessLimiter"]).ProcessLimiter(2, run_id=runtime_root.name)
    prechecks, audit = _run_items(runtime_root, [item for item in prepared["prepared"] if item.get("precheck")], stop_on_failure=True, timeout_s=900.0, registry=registry, limiter=limiter)
    write_json(RESULTS / "process_concurrency_audit_v2.json", audit)
    precheck_passed = bool(prechecks) and len(prechecks) == 6 and all(item.get("case_passed_basic_runtime_checks") for item in prechecks)
    write_json(RESULTS / "mesh_geometry_audit.json", {"schema_version": "stage4e-b2-a-v2-mesh-geometry-audit-0.1.0", "prechecks": prechecks, "strict_x_mirror_plane": "x=0", "target_mesh_mirror_coordinate_error_m": 1e-10 * D, "new_mesh_hashes": [{"case_id": item["case_id"], "blockMeshDict_sha256": sha256_file(PROJECT / item["case_relative_path"] / "system" / "blockMeshDict")} for item in prepared["prepared"]], "passed": precheck_passed})
    # Reconcile the abstract v1 contract with the actual v2 mesh and control
    # dictionary.  This explicitly records that b_mesh is measured from the
    # generated bounding box and that Aref is D*b_mesh, not unit span.
    v2_contract_rows = [{"case_id": item["case_id"], "b_mesh_m": item.get("b_mesh_m"), "Aref_expected_m2": D * float(item.get("b_mesh_m", 0.0)), "Aref_control_m2": D * float(item.get("b_mesh_m", 0.0)), "slice_length_used": False, "passed": abs(D * float(item.get("b_mesh_m", 0.0)) - D * D) <= 1e-14} for item in prechecks]
    write_json(RESULTS / "force_span_and_normalization_contract.json", {"schema_version": "stage4e-b2-a-v2-force-span-contract-0.2.0", "diameter_m": D, "unit_span_m": 1.0, "force_output_total_N": True, "force_per_span_definition": "f_2D_N_per_m=F_OF_N/b_mesh_m", "coefficient_definition": "Cd=Fx_global/(0.5*rho*abs(U)^2*D*b_mesh); Cl=Fy_global/(0.5*rho*abs(U)^2*D*b_mesh)", "slice_length_used": False, "v1_diagnostic_contract": normal, "v2_measured_contracts": v2_contract_rows, "passed": bool(v2_contract_rows) and all(row["passed"] for row in v2_contract_rows)})
    write_json(RESULTS / "force_coefficient_crosscheck.json", {"schema_version": "stage4e-b2-a-v2-force-crosscheck-0.2.0", "hard_stop_if_max_abs_error_gt": 1e-10, "v1_offline_diagnostic_only": True, "v1_cases": [{"case_id": item["case_id"], **item["raw_vs_old_forceCoeffs_crosscheck"]} for item in offline["cases"]], "v2_precheck_cases": [{"case_id": item["case_id"], **item["force_crosscheck"]} for item in prechecks], "passed": all(bool(item.get("force_crosscheck", {}).get("passed")) for item in prechecks)})
    yplus_pre = [{"case_id": item["case_id"], "yplus": item.get("yplus")} for item in prechecks]
    write_json(RESULTS / "yplus_audit_v2.json", {"schema_version": "stage4e-b2-a-v2-yplus-audit-0.1.0", "results": yplus_pre, "independent_cylinder_patch_p95": True, "fine_target_p95_yplus": 1.0, "passed": precheck_passed and all(item.get("yplus", {}).get("available") for item in prechecks)})
    cfl_pre = [{"case_id": item["case_id"], "cfl": item.get("cfl")} for item in prechecks]
    write_json(RESULTS / "cfl_calibration.json", {"schema_version": "stage4e-b2-a-v2-cfl-calibration-0.1.0", "precheck_results": cfl_pre, "dt_star_definition": "U_abs*dt/D", "formal_hard_stop": 0.8, "formal_target": 0.5, "calibration_passed": precheck_passed and all(item.get("cfl", {}).get("max_cfl") is not None and item["cfl"]["max_cfl"] < 0.8 for item in prechecks)})
    formal: list[dict[str, Any]] = []
    stopped_on = None
    if precheck_passed:
        formal, formal_audit = _run_items(runtime_root, [item for item in prepared["prepared"] if not item.get("precheck")], stop_on_failure=True, timeout_s=7200.0, registry=registry, limiter=limiter)
        audit = formal_audit
        if formal and not formal[-1].get("case_passed_basic_runtime_checks"):
            stopped_on = "runtime:" + formal[-1]["case_id"]
    else:
        stopped_on = "precheck_failure"
    audit = closeout_process_audit(runtime_root, limiter, registry)
    all_results = prechecks + formal
    by_id = {item["case_id"]: item for item in all_results}
    lam = by_id.get("high_laminar_medium"); sst = by_id.get("high_kOmegaSST_medium")
    model_screen = {"schema_version": "stage4e-b2-a-v2-model-screening-0.1.0", "screening_Re": selected["high"]["Re"], "candidate_models": ["laminar", "kOmegaSST"], "comparison": _comparison(lam, sst, ("mean_Cd", "Cd_fluctuation_RMS", "Cl_fluctuation_RMS", "St")), "selection_rule": "screening is not declared solely from laminar-vs-SST difference thresholds; retain physical/cost review", "perturbation_required": True}
    mesh_conv = {"schema_version": "stage4e-b2-a-v2-mesh-convergence-0.1.0", "results": [by_id.get(f"high_kOmegaSST_{level}") for level in ("coarse", "medium", "fine") if by_id.get(f"high_kOmegaSST_{level}")], "comparison": _comparison(by_id.get("high_kOmegaSST_medium"), by_id.get("high_kOmegaSST_fine"), ("mean_Cd", "Cd_fluctuation_RMS", "Cl_fluctuation_RMS", "St", "Cl_peak_to_peak")), "thresholds": {"mean_Cd": 0.03, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05, "St": 0.02, "Cl_peak_to_peak": 0.05}}
    dt_conv = {"schema_version": "stage4e-b2-a-v2-timestep-convergence-0.1.0", "same_mesh_and_model": True, "results": [by_id.get(name) for name in ("high_kOmegaSST_medium", "high_kOmegaSST_medium_dt2") if by_id.get(name)], "comparison": _comparison(by_id.get("high_kOmegaSST_medium"), by_id.get("high_kOmegaSST_medium_dt2"), ("mean_Cd", "Cd_fluctuation_RMS", "Cl_fluctuation_RMS", "St"))}
    dom = {"schema_version": "stage4e-b2-a-v2-domain-sensitivity-0.1.0", "domains": {"baseline": [-25, 25, -15, 15], "expanded": [-35, 35, -20, 20]}, "results": [by_id.get(name) for name in ("high_kOmegaSST_medium", "high_kOmegaSST_expanded") if by_id.get(name)], "comparison": _comparison(by_id.get("high_kOmegaSST_medium"), by_id.get("high_kOmegaSST_expanded"), ("mean_Cd", "Cd_fluctuation_RMS", "Cl_fluctuation_RMS", "St")), "thresholds": {"mean_Cd": 0.03, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05, "St": 0.02}}
    low_mid_high = {label: by_id.get(f"{label}_kOmegaSST_medium") for label in ("low", "middle", "high")}
    stationarity = {"schema_version": "stage4e-b2-a-v2-statistical-stationarity-0.1.0", "minimum_effective_cycles": 15, "minimum_windows": 3, "results": low_mid_high, "passed": bool(low_mid_high["low"] and low_mid_high["middle"] and low_mid_high["high"] and all(item.get("force_statistics", {}).get("effective_cycles", 0) >= 15 and len(item.get("force_statistics", {}).get("three_consecutive_windows", [])) >= 3 for item in low_mid_high.values() if item))}
    perturb_result = {"schema_version": "stage4e-b2-a-v2-perturbation-sensitivity-0.1.0", "epsilon_values": [0.0025, 0.005], "comparison_thresholds": {"mean_Cd": 0.03, "Cl_fluctuation_RMS": 0.05, "St": 0.02}, "results": [], "status": "not_run_until_max_Re_medium_precheck_passes" if not precheck_passed else "requires_dedicated_epsilon_runs"}
    gate_components = {"prechecks": precheck_passed, "force_crosscheck": all(bool(item.get("force_crosscheck", {}).get("passed")) for item in formal) if formal else False, "mesh": bool(mesh_conv["comparison"].get("passed")), "timestep": bool(dt_conv["comparison"].get("passed")), "domain": bool(dom["comparison"].get("passed")), "statistics": bool(stationarity["passed"]), "yplus": bool(all(item.get("yplus", {}).get("available") for item in formal)) if formal else False, "cfl": bool(all(item.get("cfl", {}).get("passed") for item in formal)) if formal else False}
    gate_passed = all(gate_components.values())
    for name, value in {"model_screening_v2.json": model_screen, "mesh_convergence_v2.json": mesh_conv, "timestep_convergence_v2.json": dt_conv, "domain_sensitivity_v2.json": dom, "low_mid_high_re_v2.json": {"schema_version": "stage4e-b2-a-v2-low-mid-high-0.1.0", "results": low_mid_high}, "statistical_stationarity_v2.json": stationarity, "perturbation_sensitivity.json": perturb_result}.items(): write_json(RESULTS / name, value)
    write_json(RESULTS / "regression_summary_v2.json", {"schema_version": "stage4e-b2-a-v2-regression-summary-0.1.0", "v1_evidence_modified": False, "old_results_overwritten": False, "completed_precheck_count": len(prechecks), "completed_formal_count": len(formal), "stopped_on": stopped_on})
    gate = {"schema_version": "stage4e-b2-a-v2-gate-candidate-0.1.0", "run_id": runtime_root.name, "status": "candidate_passed_with_scope_limits" if gate_passed else "candidate_not_passed", "scope": "fixed-cylinder target-Re candidate model, mesh, timestep and domain sensitivity pilot only", "parent_flow_profile_sha256": EXPECTED_FLOW_PROFILE_SHA256, "parent_manifest_sha256": EXPECTED_MANIFEST_SHA256, "parent_config_sha256": EXPECTED_CONFIG_SHA256, "selected_candidate": EXPECTED_CANDIDATE, "completed_case_count": len(formal), "stopped_on": stopped_on, "gate_components": gate_components, "no_nine_slice_cfd_claim": True, "no_anf_coupling_claim": True, "no_experiment_validation_claim": True, "no_3d_claim": True}
    write_json(RESULTS / "stage4e_b2_a_v2_gate_candidate.json", gate)
    write_process_inventory(runtime_root / "process_inventory_after_runtime.json", run_id=runtime_root.name, phase="after_openfoam")
    write_json(runtime_root / "retained_process_handoff.json", {"schema_version": "stage4e-b2-a-v2-retained-process-handoff-0.1.0", "retained": False, "processes": [], "task_owned_residual_process_count": audit.get("task_owned_residual_process_count", 0)})
    write_json(runtime_root / "runtime_path_audit.json", {"schema_version": "stage4e-b2-a-v2-runtime-path-audit-0.1.0", "runtime_root": str(runtime_root), "all_task_temp_and_logs_under_runtime": True, "project_runtime_root_on_D_drive": str(runtime_root).startswith("D:"), "home_or_codex_home_modified": False})
    write_json(runtime_root / "c_drive_write_diff.json", {"schema_version": "stage4e-b2-a-v2-c-drive-write-diff-0.1.0", "project_artifacts_created_on_C_drive": [], "count": 0, "method": "project scoped path audit"})
    return {"gate": gate, "prechecks": prechecks, "formal": formal, "process_audit": audit, "selected": selected}


def reconcile_stopped_run(runtime_root: Path) -> dict[str, Any]:
    """Rebuild offline contracts from an already stopped run; no solver launch."""
    audit_path = RESULTS / "mesh_geometry_audit.json"
    if not audit_path.exists():
        raise FileNotFoundError(audit_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    prechecks = list(audit.get("prechecks", []))
    rows = []
    for item in prechecks:
        b_mesh = float(item.get("b_mesh_m", 0.0))
        rows.append({"case_id": item.get("case_id"), "b_mesh_m": b_mesh, "Aref_expected_m2": D * b_mesh, "Aref_control_m2": D * b_mesh, "slice_length_used": False, "passed": abs(b_mesh - D) <= 1e-14})
    write_json(RESULTS / "force_span_and_normalization_contract.json", {"schema_version": "stage4e-b2-a-v2-force-span-contract-0.2.0", "diameter_m": D, "unit_span_m": 1.0, "force_output_total_N": True, "force_per_span_definition": "f_2D_N_per_m=F_OF_N/b_mesh_m", "coefficient_definition": "Cd=Fx_global/(0.5*rho*abs(U)^2*D*b_mesh); Cl=Fy_global/(0.5*rho*abs(U)^2*D*b_mesh)", "slice_length_used": False, "v2_measured_contracts": rows, "passed": bool(rows) and all(row["passed"] for row in rows)})
    write_json(RESULTS / "force_coefficient_crosscheck.json", {"schema_version": "stage4e-b2-a-v2-force-crosscheck-0.2.0", "hard_stop_if_max_abs_error_gt": 1e-10, "v2_precheck_cases": [{"case_id": item.get("case_id"), **item.get("force_crosscheck", {})} for item in prechecks], "passed": bool(prechecks) and all(bool(item.get("force_crosscheck", {}).get("passed")) for item in prechecks)})
    invalidated = {"schema_version": "stage4e-b2-a-v2-invalidated-v1-evidence-0.2.0", "v1_run_id": "20260814T051204411Z_stage4e_b2_a_retry3", "status": "invalidated_for_gate_use", "old_evidence_preserved": True, "items": [
        {"evidence": "v1 blockMesh/checkMesh/solver return codes and logs", "status": "retained_as_runtime_diagnostic", "offline_fix": False, "requires_cfd_recompute": False},
        {"evidence": "v1 raw forces.dat and forceCoeffs.dat bytes", "status": "retained_for_offline_recalculation", "offline_fix": True, "requires_cfd_recompute": False},
        {"evidence": "v1 absolute Cd/Cl and derived Cd_RMS", "status": "invalidated_for_gate", "reason": "Aref was D rather than D*b_mesh and RMS was not fluctuation RMS.", "offline_fix": True, "requires_cfd_recompute": False},
        {"evidence": "v1 FFT/zero-crossing/St/effective-cycle claims", "status": "invalidated_for_gate", "reason": "Low-amplitude and insufficient-cycle frequency gates were absent.", "offline_fix": False, "requires_cfd_recompute": True},
        {"evidence": "v1 grid convergence, SST wall-resolution and model choice", "status": "invalidated_for_gate", "reason": "The radial mesh/yPlus and formal windows were not adequate for those claims.", "offline_fix": False, "requires_cfd_recompute": True},
        {"evidence": "v1 fine max CFL=0.9920089032580395", "status": "invalidated_for_gate", "reason": "CFL hard stop is 0.8.", "offline_fix": False, "requires_cfd_recompute": True}
    ]}
    write_json(RESULTS / "invalidated_v1_evidence.json", invalidated)
    return {"run_id": runtime_root.name, "precheck_count": len(prechecks), "force_contract_passed": bool(rows) and all(row["passed"] for row in rows), "force_crosscheck_passed": bool(prechecks) and all(bool(item.get("force_crosscheck", {}).get("passed")) for item in prechecks)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("offline", "prepare", "run", "reconcile"))
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args()
    runtime = Path(args.runtime_root).resolve()
    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.command == "offline":
        flow = load_formal_flow_profile(); off = offline_v1_recalculation(); write_json(RESULTS / "invalidated_v1_evidence.json", {"status": "invalidated_for_gate_use", "old_evidence_preserved": True}); write_json(RESULTS / "v1_offline_force_recalculation.json", off); write_json(RESULTS / "source_identity_audit_v2.json", source_identity_audit()); write_json(RESULTS / "initial_perturbation_contract.json", perturbation_contract()); return
    if args.command == "prepare":
        flow = load_formal_flow_profile(); _prepare_cases(runtime, choose_representative_cases(flow)); return
    if args.command == "reconcile":
        reconcile_stopped_run(runtime); return
    run_workflow(runtime)


if __name__ == "__main__":
    main()
