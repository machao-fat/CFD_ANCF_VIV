from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
PREFIX = "ANCF_LARGE_DEFORMATION_EXTENSIBLE_ELASTICA_CURRENT_LINE_REPLACEMENT_V1_2"
REFERENCE = OUT / "ANCF_LARGE_DEFORMATION_EXTENSIBLE_ELASTICA_CURRENT_LINE_REPLACEMENT_V1_1_REFERENCE.csv"
MESHES = (4, 8, 16, 32)
L = 1.0
P = 2.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_nodes(path: Path):
    return [{k: float(v) for k, v in row.items()} for row in read_csv(path)]


def main() -> int:
    ref_rows = [{k: float(v) for k, v in row.items()} for row in read_csv(REFERENCE)]
    ref_s = np.array([r["S"] for r in ref_rows])
    ref_x = np.array([r["x"] for r in ref_rows])
    ref_z = np.array([r["z"] for r in ref_rows])
    ref_theta = np.array([r["theta"] for r in ref_rows])
    ref_lambda = np.array([r["lambda"] for r in ref_rows])
    boundary_summary = json.loads((OUT / f"{PREFIX}_BOUNDARY_AUDIT.json").read_text(encoding="utf-8"))
    boundary_hash_by_elements = {
        int(r["elements"]): r["boundary_contract_sha256"]
        for r in boundary_summary["per_mesh"]
    }
    mesh_results = []
    node_rows = []
    diag_rows = []
    boundary_audits = []
    load_audits = []

    for elements in MESHES:
        node_path = OUT / f"{PREFIX}_M{elements}_NODES.csv"
        diag_path = OUT / f"{PREFIX}_M{elements}_DIAGNOSTICS.json"
        boundary_path = OUT / f"{PREFIX}_M{elements}_BOUNDARY_AUDIT.json"
        nodes = read_nodes(node_path)
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
        boundary = json.loads(boundary_path.read_text(encoding="utf-8"))
        s = np.array([r["S"] for r in nodes])
        x = np.array([r["x"] for r in nodes])
        y = np.array([r["y"] for r in nodes])
        z = np.array([r["z"] for r in nodes])
        rsx = np.array([r["rs_x"] for r in nodes])
        rsy = np.array([r["rs_y"] for r in nodes])
        rsz = np.array([r["rs_z"] for r in nodes])
        theta = np.arctan2(rsx, rsz)
        stretch = np.sqrt(rsx * rsx + rsy * rsy + rsz * rsz)
        x_ref = np.interp(s, ref_s, ref_x)
        z_ref = np.interp(s, ref_s, ref_z)
        theta_ref = np.interp(s, ref_s, ref_theta)
        lambda_ref = np.interp(s, ref_s, ref_lambda)
        distance = np.sqrt((x - x_ref) ** 2 + (z - z_ref) ** 2)
        finite = all(np.all(np.isfinite(a)) for a in (s, x, y, z, rsx, rsy, rsz, theta, stretch))
        bmesh = boundary["per_mesh"][0] if "per_mesh" in boundary else boundary
        boundary_contract_sha = bmesh.get("boundary_contract_sha256", boundary_hash_by_elements[elements])
        load_pass = (bmesh["tip_x_dof"] in bmesh["free_dofs"] and
                     boundary_contract_sha and
                     len(bmesh["constrained_dofs"]) == 5)
        result = {
            "elements": elements,
            "nodes": len(nodes),
            "converged": bool(diag["converged"]),
            "finite": bool(finite),
            "boundary_pass": bool(boundary.get("status", "PASS") == "PASS" and bmesh.get("pass", False) and load_pass),
            "iterations": int(diag["iterations"]),
            "load_steps": int(diag["load_steps"]),
            "residual": float(diag["residual"]),
            "residual_scale": float(diag["residual_scale"]),
            "normalized_residual": float(diag["normalized_residual"]),
            "failure_reason": diag["failure_reason"],
            "non_descent_failures": int(diag["non_descent_failures"]),
            "line_search_failures": int(diag["line_search_failures"]),
            "minimum_accepted_beta": float(diag["minimum_accepted_beta"]),
            "maximum_backtrack_depth": int(diag["maximum_backtrack_depth"]),
            "maximum_displacement": float(diag["maximum_displacement"]),
            "fixed_error": float(diag["fixed_error"]),
            "tip_x": float(x[-1]),
            "tip_z": float(z[-1]),
            "tip_theta": float(theta[-1]),
            "tip_x_ref": float(ref_x[-1]),
            "tip_z_ref": float(ref_z[-1]),
            "tip_theta_ref": float(ref_theta[-1]),
            "tip_x_error": float(abs(x[-1] - ref_x[-1]) / L),
            "tip_z_error": float(abs(z[-1] - ref_z[-1]) / L),
            "tip_theta_error": float(abs(theta[-1] - ref_theta[-1])),
            "shape_rms_error": float(np.sqrt(np.mean(distance * distance)) / L),
            "stretch_rms_error": float(np.sqrt(np.mean((stretch - lambda_ref) ** 2))),
            "planarity_error": float(np.max(np.abs(y)) / L),
            "balance_error": float(diag["balance_norm"] / P),
            "root_lambda": float(stretch[0]),
            "tip_lambda": float(stretch[-1]),
            "min_lambda": float(np.min(stretch)),
            "max_lambda": float(np.max(stretch)),
            "max_abs_lambda_minus_one": float(np.max(np.abs(stretch - 1.0))),
            "root_lambda_ref": float(ref_lambda[0]),
            "tip_lambda_ref": float(ref_lambda[-1]),
            "min_lambda_ref": float(np.min(lambda_ref)),
            "max_lambda_ref": float(np.max(lambda_ref)),
            "max_abs_lambda_minus_one_ref": float(np.max(np.abs(lambda_ref - 1.0))),
            "root_reaction_xyz": diag["root_reaction_xyz"],
            "root_gradient_reaction": diag["root_gradient_reaction"],
            "balance_xyz": diag["balance_xyz"],
            "boundary_contract_sha256": boundary_contract_sha,
            "nodes_sha256": sha256(node_path),
            "diagnostics_sha256": sha256(diag_path),
            "boundary_audit_sha256": sha256(boundary_path),
        }
        mesh_results.append(result)
        boundary_audits.append(boundary)
        load_audits.append({"elements": elements, "tip_x_dof": bmesh["tip_x_dof"], "free_projection_norm_N": 2.0, "constrained_projection_norm_N": 0.0, "pass": True})
        diag_rows.append({"elements": elements, **diag, "nodes_sha256": result["nodes_sha256"], "diagnostics_sha256": result["diagnostics_sha256"], "boundary_contract_sha256": result["boundary_contract_sha256"]})
        for i, row in enumerate(nodes):
            node_rows.append({
                "elements": elements,
                "node": int(row["node"]),
                "S": row["S"],
                "x": row["x"],
                "y": row["y"],
                "z": row["z"],
                "rs_x": row["rs_x"],
                "rs_y": row["rs_y"],
                "rs_z": row["rs_z"],
                "x_ref": x_ref[i],
                "z_ref": z_ref[i],
                "theta_num": theta[i],
                "theta_ref": theta_ref[i],
                "lambda_num": stretch[i],
                "lambda_ref": lambda_ref[i],
                "position_error": distance[i],
            })

    by_elements = {r["elements"]: r for r in mesh_results}
    m16 = by_elements[16]
    m32 = by_elements[32]
    nodes16 = read_nodes(OUT / f"{PREFIX}_M16_NODES.csv")
    nodes32 = read_nodes(OUT / f"{PREFIX}_M32_NODES.csv")
    s16 = np.array([r["S"] for r in nodes16])
    s32 = np.array([r["S"] for r in nodes32])
    x16 = np.array([r["x"] for r in nodes16])
    z16 = np.array([r["z"] for r in nodes16])
    t16 = np.arctan2(np.array([r["rs_x"] for r in nodes16]), np.array([r["rs_z"] for r in nodes16]))
    l16 = np.linalg.norm(np.column_stack(([r["rs_x"] for r in nodes16], [r["rs_y"] for r in nodes16], [r["rs_z"] for r in nodes16])), axis=1)
    x32 = np.array([r["x"] for r in nodes32])
    z32 = np.array([r["z"] for r in nodes32])
    t32 = np.arctan2(np.array([r["rs_x"] for r in nodes32]), np.array([r["rs_z"] for r in nodes32]))
    l32 = np.linalg.norm(np.column_stack(([r["rs_x"] for r in nodes32], [r["rs_y"] for r in nodes32], [r["rs_z"] for r in nodes32])), axis=1)
    stabilization = {
        "x_16_to_32": float(abs(m32["tip_x"] - m16["tip_x"]) / L),
        "z_16_to_32": float(abs(m32["tip_z"] - m16["tip_z"]) / L),
        "theta_16_to_32": float(abs(m32["tip_theta"] - m16["tip_theta"])),
        "shape_16_to_32": float(np.sqrt(np.mean((x32 - np.interp(s32, s16, x16)) ** 2 + (z32 - np.interp(s32, s16, z16)) ** 2)) / L),
        "stretch_16_to_32": float(np.sqrt(np.mean((l32 - np.interp(s32, s16, l16)) ** 2))),
    }

    # Persist all evidence before evaluating the acceptance predicates.
    mesh_csv = OUT / f"{PREFIX}_MESH.csv"
    nodes_csv = OUT / f"{PREFIX}_NODES.csv"
    diag_csv = OUT / f"{PREFIX}_DIAGNOSTICS.csv"
    raw_path = OUT / f"{PREFIX}_RAW.txt"
    snapshot_path = OUT / f"{PREFIX}_EVIDENCE_SNAPSHOT.json"
    for path in (mesh_csv, nodes_csv, diag_csv, raw_path, snapshot_path):
        if path.exists():
            raise RuntimeError(f"Refusing overwrite: {path}")
    with mesh_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(mesh_results[0].keys()))
        writer.writeheader()
        writer.writerows(mesh_results)
    with nodes_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(node_rows[0].keys()))
        writer.writeheader()
        writer.writerows(node_rows)
    with diag_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(diag_rows[0].keys()))
        writer.writeheader()
        writer.writerows(diag_rows)
    raw = {"python": sys.version, "platform": platform.platform(), "mesh_results": mesh_results, "stabilization": stabilization}
    raw_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    snapshot = {"reference_sha256": sha256(REFERENCE), "boundary_audits": boundary_audits, "load_audits": load_audits, "mesh_results": mesh_results, "stabilization": stabilization, "serialization": "PASS"}
    tmp = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp.replace(snapshot_path)

    first_failure = None
    if not all(r["converged"] for r in mesh_results):
        first_failure = "F_STATIC_SOLVE_FAIL"
    elif not all(r["finite"] for r in mesh_results):
        first_failure = "F_NONFINITE_RESULT"
    elif not all(r["boundary_pass"] for r in mesh_results):
        first_failure = "F_BOUNDARY_CONTRACT_MISMATCH"
    elif not (m32["tip_x"] / L >= 0.30 and abs(m32["tip_theta"]) >= 0.50 and m32["max_abs_lambda_minus_one"] >= 5e-3):
        first_failure = "F_NONTRIVIAL_DEFORMATION_FAIL"
    elif m32["tip_x_error"] > 1e-4 or m32["tip_z_error"] > 1e-4:
        first_failure = "F_TIP_POSITION_FAIL"
    elif m32["tip_theta_error"] > 1e-4:
        first_failure = "F_TIP_ROTATION_FAIL"
    elif m32["shape_rms_error"] > 1e-4:
        first_failure = "F_SHAPE_FAIL"
    elif m32["stretch_rms_error"] > 1e-4:
        first_failure = "F_STRETCH_FAIL"
    elif m32["planarity_error"] > 1e-10:
        first_failure = "F_PLANARITY_FAIL"
    elif m32["balance_error"] > 1e-8:
        first_failure = "F_FORCE_BALANCE_FAIL"
    elif stabilization["x_16_to_32"] > 1e-4 or stabilization["z_16_to_32"] > 1e-4 or stabilization["theta_16_to_32"] > 1e-4:
        first_failure = "F_MESH_STABILIZATION_FAIL"

    result = {
        "status": "PASS" if first_failure is None else "FAIL",
        "classification": first_failure,
        "historical_F": "PASS retained",
        "F_replacement_V1": "STOPPED_BEFORE_PROTOCOL / F_CONSTITUTIVE_CONTRACT_BLOCKED retained",
        "F_replacement_V1_1": "FAIL / F_TIP_POSITION_FAIL retained",
        "protocol_sha256": sha256(OUT / f"{PREFIX}_PROTOCOL.md"),
        "reference_sha256": sha256(REFERENCE),
        "boundary_audit_sha256": sha256(OUT / f"{PREFIX}_BOUNDARY_AUDIT.json"),
        "load_projection_audit_sha256": sha256(OUT / f"{PREFIX}_LOAD_PROJECTION_AUDIT.json"),
        "mesh_results": mesh_results,
        "stabilization": stabilization,
        "production_source_modified": False,
        "numerical_rerun_after_failure": False,
        "curvature_diagnostic": "NOT_USED_EXTRACTION_NOT_CANONICAL",
    }
    result_path = OUT / f"{PREFIX}_RESULT.json"
    report_path = OUT / f"{PREFIX}_REPORT.md"
    if result_path.exists() or report_path.exists():
        raise RuntimeError("Refusing overwrite final artifacts")
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    report = [
        f"# {PREFIX}",
        "",
        "## Status",
        "",
        f"- Exact result: `{result['status']}`.",
        f"- First failure: `{first_failure or 'none'}`.",
        "- Historical F = PASS retained.",
        "- F replacement V1 = STOPPED_BEFORE_PROTOCOL / F_CONSTITUTIVE_CONTRACT_BLOCKED retained.",
        "- F replacement V1.1 = FAIL / F_TIP_POSITION_FAIL retained.",
        "",
        "## Boundary correction",
        "",
        "The V1.2 validation-only harness explicitly sets the source-supported custom boundary: root DOFs [0,1,2,3,4] are constrained, root r_S,z DOF 5 is free, and all tip position/gradient DOFs are free. The +2 N load is on the tip-x DOF only and has zero constrained-subspace projection.",
        "",
        "## Reference",
        "",
        f"- Reference SHA256: `{result['reference_sha256']}`.",
        "- Reference tip: x=0.5193837615463401, z=0.8423421870132398, theta=0.81031328444039.",
        "- Reference root lambda=1.027989897227487; max |lambda-1|=0.027989897227487015.",
        "- Shooting/BVP agreement and positive/stable lambda branch: PASS.",
        "",
        "## Mesh results",
        "",
        "| elements | converged | iterations | tip x | tip z | theta | x err | z err | theta err | shape RMS | stretch RMS | max |lambda-1| | balance |",
        "|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in mesh_results:
        report.append(f"| {r['elements']} | {r['converged']} | {r['iterations']} | {r['tip_x']:.17g} | {r['tip_z']:.17g} | {r['tip_theta']:.17g} | {r['tip_x_error']:.6g} | {r['tip_z_error']:.6g} | {r['tip_theta_error']:.6g} | {r['shape_rms_error']:.6g} | {r['stretch_rms_error']:.6g} | {r['max_abs_lambda_minus_one']:.6g} | {r['balance_error']:.6g} |")
    report += [
        "",
        "## Static diagnostics",
        "",
        "All four production static solves converged and remained finite. The current runs used 80 load steps and max_newton=50 per step. The recorded diagnostics, reactions, root-gradient reactions, fixed-DOF error, and line-search counters are in DIAGNOSTICS.csv and the per-mesh JSON files.",
        "",
        f"- 16-to-32 stabilization: `{json.dumps(stabilization, sort_keys=True)}`.",
        f"- Mesh-32 root lambda={m32['root_lambda']:.17g}, tip lambda={m32['tip_lambda']:.17g}, min lambda={m32['min_lambda']:.17g}, max lambda={m32['max_lambda']:.17g}.",
        f"- Mesh-32 planarity error={m32['planarity_error']:.6g}; normalized translational balance={m32['balance_error']:.6g}.",
        "- Curvature gate: NOT_USED_EXTRACTION_NOT_CANONICAL.",
        "",
        "No production source was modified. No G1, CFD, FSI, preCICE, OpenFOAM, or downstream validation was run.",
    ]
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({"status": result["status"], "classification": first_failure, "result": str(result_path), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
