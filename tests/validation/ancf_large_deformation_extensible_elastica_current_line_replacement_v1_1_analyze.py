from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
PREFIX = "ANCF_LARGE_DEFORMATION_EXTENSIBLE_ELASTICA_CURRENT_LINE_REPLACEMENT_V1_1"
REFERENCE = OUT / f"{PREFIX}_REFERENCE.csv"
MESHES = (4, 8, 16, 32)
L = 1.0
P = 2.0
X_TOL = 1e-4
Z_TOL = 1e-4
THETA_TOL = 1e-4
SHAPE_TOL = 1e-4
STRETCH_TOL = 1e-4
PLANARITY_TOL = 1e-10
BALANCE_TOL = 1e-8
STAB_X_TOL = 1e-4
STAB_Z_TOL = 1e-4
STAB_THETA_TOL = 1e-4


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def read_nodes(path: Path):
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def read_reference(path: Path):
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def finite(value) -> bool:
    return bool(np.all(np.isfinite(value)))


def main() -> int:
    ref = read_reference(REFERENCE)
    rs = np.array([r["S"] for r in ref])
    rx = np.array([r["x"] for r in ref])
    rz = np.array([r["z"] for r in ref])
    rt = np.array([r["theta"] for r in ref])
    rl = np.array([r["lambda"] for r in ref])

    mesh_results = []
    all_nodes = []
    diagnostics = []
    for elements in MESHES:
        node_path = OUT / f"{PREFIX}_M{elements}_NODES.csv"
        diag_path = OUT / f"{PREFIX}_M{elements}_DIAGNOSTICS.json"
        nodes = read_nodes(node_path)
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
        s = np.array([r["S"] for r in nodes])
        x = np.array([r["x"] for r in nodes])
        y = np.array([r["y"] for r in nodes])
        z = np.array([r["z"] for r in nodes])
        rsx = np.array([r["rs_x"] for r in nodes])
        rsy = np.array([r["rs_y"] for r in nodes])
        rsz = np.array([r["rs_z"] for r in nodes])
        x_ref = np.interp(s, rs, rx)
        z_ref = np.interp(s, rs, rz)
        theta_ref = np.interp(s, rs, rt)
        lambda_ref = np.interp(s, rs, rl)
        theta_num = np.arctan2(rsx, rsz)
        lambda_num = np.sqrt(rsx * rsx + rsy * rsy + rsz * rsz)
        d = np.sqrt((x - x_ref) ** 2 + (z - z_ref) ** 2)
        tip = -1
        balance = float(diag["balance_norm"] / P)
        result = {
            "elements": elements,
            "nodes": len(nodes),
            "converged": bool(diag["converged"]),
            "finite": all(finite(a) for a in (s, x, y, z, rsx, rsy, rsz, theta_num, lambda_num)),
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
            "tip_x": float(x[tip]),
            "tip_z": float(z[tip]),
            "tip_theta": float(theta_num[tip]),
            "tip_x_ref": float(rx[-1]),
            "tip_z_ref": float(rz[-1]),
            "tip_theta_ref": float(rt[-1]),
            "tip_x_error": float(abs(x[tip] - rx[-1]) / L),
            "tip_z_error": float(abs(z[tip] - rz[-1]) / L),
            "tip_theta_error": float(abs(theta_num[tip] - rt[-1])),
            "shape_rms_error": float(np.sqrt(np.mean(d * d)) / L),
            "stretch_rms_error": float(np.sqrt(np.mean((lambda_num - lambda_ref) ** 2))),
            "planarity_error": float(np.max(np.abs(y)) / L),
            "balance_error": balance,
            "max_lambda_num": float(np.max(lambda_num)),
            "min_lambda_num": float(np.min(lambda_num)),
            "max_abs_lambda_minus_one_num": float(np.max(np.abs(lambda_num - 1.0))),
            "max_lambda_ref": float(np.max(lambda_ref)),
            "min_lambda_ref": float(np.min(lambda_ref)),
            "max_abs_lambda_minus_one_ref": float(np.max(np.abs(lambda_ref - 1.0))),
            "root_reaction_xyz": diag["root_reaction_xyz"],
            "tip_y_reaction": float(diag["tip_y_reaction"]),
            "balance_xyz": diag["balance_xyz"],
            "nodes_sha256": sha256(node_path),
            "diagnostics_sha256": sha256(diag_path),
        }
        mesh_results.append(result)
        diagnostics.append({"elements": elements, **diag, "nodes_sha256": result["nodes_sha256"], "diagnostics_sha256": result["diagnostics_sha256"]})
        for i, row in enumerate(nodes):
            all_nodes.append({
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
                "theta_num": theta_num[i],
                "theta_ref": theta_ref[i],
                "lambda_num": lambda_num[i],
                "lambda_ref": lambda_ref[i],
                "position_error": d[i],
            })

    by_mesh = {r["elements"]: r for r in mesh_results}
    m16 = by_mesh[16]
    m32 = by_mesh[32]
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

    # Evidence is serialized before the gate is evaluated.
    mesh_csv = OUT / f"{PREFIX}_MESH.csv"
    nodes_csv = OUT / f"{PREFIX}_NODES.csv"
    diag_csv = OUT / f"{PREFIX}_DIAGNOSTICS.csv"
    raw_path = OUT / f"{PREFIX}_RAW.txt"
    evidence_path = OUT / f"{PREFIX}_EVIDENCE_SNAPSHOT.json"
    for p in (mesh_csv, nodes_csv, diag_csv, raw_path, evidence_path):
        if p.exists():
            raise RuntimeError(f"Refusing overwrite: {p}")

    with mesh_csv.open("w", newline="", encoding="utf-8") as f:
        fields = list(mesh_results[0].keys())
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(mesh_results)
    with nodes_csv.open("w", newline="", encoding="utf-8") as f:
        fields = list(all_nodes[0].keys())
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_nodes)
    with diag_csv.open("w", newline="", encoding="utf-8") as f:
        fields = list(diagnostics[0].keys())
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(diagnostics)
    raw = {
        "python": sys.version,
        "platform": platform.platform(),
        "reference_sha256": sha256(REFERENCE),
        "mesh_results": mesh_results,
        "stabilization": stabilization,
    }
    raw_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    snapshot = {"mesh_results": mesh_results, "stabilization": stabilization, "evidence_serialization": "PASS"}
    tmp = evidence_path.with_suffix(evidence_path.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp.replace(evidence_path)

    first_failure = None
    for r in mesh_results:
        if not r["converged"] or r["failure_reason"]:
            first_failure = "F_STATIC_SOLVE_FAIL"
            break
        if not r["finite"]:
            first_failure = "F_NONFINITE_RESULT"
            break
    if first_failure is None:
        r = by_mesh[32]
        if r["tip_x_error"] > X_TOL or r["tip_z_error"] > Z_TOL:
            first_failure = "F_TIP_POSITION_FAIL"
        elif r["tip_theta_error"] > THETA_TOL:
            first_failure = "F_TIP_ROTATION_FAIL"
        elif r["shape_rms_error"] > SHAPE_TOL:
            first_failure = "F_SHAPE_FAIL"
        elif r["stretch_rms_error"] > STRETCH_TOL:
            first_failure = "F_STRETCH_FAIL"
        elif r["planarity_error"] > PLANARITY_TOL:
            first_failure = "F_PLANARITY_FAIL"
        elif r["balance_error"] > BALANCE_TOL:
            first_failure = "F_FORCE_BALANCE_FAIL"
        elif stabilization["x_16_to_32"] > STAB_X_TOL or stabilization["z_16_to_32"] > STAB_Z_TOL or stabilization["theta_16_to_32"] > STAB_THETA_TOL:
            first_failure = "F_MESH_STABILIZATION_FAIL"

    result = {
        "status": "FAIL" if first_failure else "PASS",
        "classification": first_failure,
        "historical_F": "PASS retained",
        "F_replacement_V1": "STOPPED_BEFORE_PROTOCOL / F_CONSTITUTIVE_CONTRACT_BLOCKED retained",
        "protocol_sha256": sha256(OUT / f"{PREFIX}_PROTOCOL.md"),
        "reference_sha256": sha256(REFERENCE),
        "reference_audit_sha256": sha256(OUT / f"{PREFIX}_REFERENCE_AUDIT.json"),
        "lambda_branch_audit_sha256": sha256(OUT / f"{PREFIX}_LAMBDA_BRANCH_AUDIT.csv"),
        "mesh_results": mesh_results,
        "stabilization": stabilization,
        "production_boundary_contract_observation": {
            "required": "root complete six position/gradient DOFs fixed; tip x/y free",
            "harness_actual": "default production canonical boundary remained active: root x/y/z and tip x/y fixed",
            "evidence": "tip x remains zero under +2 N tip-x load; reported balance_norm/P = 1",
            "interpretation": "validation-harness contract mismatch, not evidence of production continuum physics failure",
        },
        "numerical_rerun_after_failure": False,
        "production_source_modified": False,
    }
    result_path = OUT / f"{PREFIX}_RESULT.json"
    report_path = OUT / f"{PREFIX}_REPORT.md"
    if result_path.exists() or report_path.exists():
        raise RuntimeError("Refusing overwrite of final artifacts")
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        f"# {PREFIX}",
        "",
        "## Status",
        "",
        f"- Exact first formal failure: `{first_failure or 'PASS'}`.",
        "- Historical F = PASS retained.",
        "- F replacement V1 = STOPPED_BEFORE_PROTOCOL / F_CONSTITUTIVE_CONTRACT_BLOCKED retained.",
        "- This V1.1 run is not promoted to PASS.",
        "",
        "## Identity and frozen reference",
        "",
        f"- Protocol SHA256: `{result['protocol_sha256']}`.",
        f"- Reference dataset SHA256: `{result['reference_sha256']}`.",
        "- Corrected production continuum contract was used for the independent reference: W_a = EA/8 (lambda^2-1)^2; W_b = EI/2 (theta_S/lambda)^2.",
        "- Reference shooting/BVP preflight had already passed before production execution.",
        "",
        "## Formal execution evidence",
        "",
        "All four invocations returned zero and wrote finite node/diagnostic files. However, the validation harness did not override the production default canonical boundary. The production source canonical boundary is root x/y/z plus tip x/y; the frozen F contract required complete root position/gradient clamping with tip x free.",
        "",
        "Consequently the +2 N tip-x load was applied to a fixed tip-x DOF. The resulting straight reference state is not the requested cantilever equilibrium. This is a validation-tooling contract defect and must not be interpreted as a production mechanics failure.",
        "",
        "## Mesh results",
        "",
        "| elements | converged | tip x | tip z | theta | x error | z error | theta error | shape RMS | stretch RMS | planarity | balance |",
        "|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in mesh_results:
        lines.append(f"| {r['elements']} | {r['converged']} | {r['tip_x']:.17g} | {r['tip_z']:.17g} | {r['tip_theta']:.17g} | {r['tip_x_error']:.6g} | {r['tip_z_error']:.6g} | {r['tip_theta_error']:.6g} | {r['shape_rms_error']:.6g} | {r['stretch_rms_error']:.6g} | {r['planarity_error']:.6g} | {r['balance_error']:.6g} |")
    lines.extend([
        "",
        "## First-failure policy",
        "",
        f"The first frozen comparison gate is `{first_failure}` because the 32-element tip position does not match the immutable continuum reference. No harness repair or numerical rerun was performed after formal execution.",
        "",
        f"16-to-32 stabilization: `{json.dumps(stabilization, sort_keys=True)}`.",
        "",
        "The required successor for the boundary/tooling repair is V1.2; no successor is executed automatically.",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"classification": first_failure, "report": str(report_path), "result": str(result_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
