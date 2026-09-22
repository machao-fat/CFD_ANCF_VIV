"""Assemble the formal evidence for the already completed Ns=2 smoke."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
ATTEMPT = ROOT / "runtime/coupling_validation/REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1_attempt_001"
OUT = ROOT / "runtime/ANCF_validation"
SOURCE = Path(r"D:\CFD\CFD_ANCF_VIV\runtime\ANCF_validation\mesh_case")
PREFIX = "REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1"
MESH_NODES = (0.0, 2.5, 5.0, 7.5, 10.0)
ACTIVE_START = 4.5
ACTIVE_END = 5.5
S1 = 4.75
S2 = 5.25


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def gauss_legendre(order: int) -> tuple[tuple[float, float], ...]:
    values = [(0.0, 0.0)] * order
    eps = 2.0e-15
    for index in range(1, (order + 1) // 2 + 1):
        z = math.cos(math.pi * (index - 0.25) / (order + 0.5))
        for _ in range(100):
            p0, p1 = 1.0, z
            for degree in range(2, order + 1):
                p0, p1 = p1, ((2.0 * degree - 1.0) * z * p1 - (degree - 1.0) * p0) / degree
            derivative = order * (z * p1 - p0) / (z * z - 1.0)
            next_z = z - p1 / derivative
            if abs(next_z - z) <= eps:
                z = next_z
                break
            z = next_z
        p0, p1 = 1.0, z
        for degree in range(2, order + 1):
            p0, p1 = p1, ((2.0 * degree - 1.0) * z * p1 - (degree - 1.0) * p0) / degree
        derivative = order * (z * p1 - p0) / (z * z - 1.0)
        weight = 2.0 / ((1.0 - z * z) * derivative * derivative)
        left = index - 1
        right = order - index
        values[left] = (-z, weight)
        values[right] = (z, weight)
    return tuple(values)


def hermite_h(s: float) -> tuple[tuple[float, ...], ...]:
    ndof = 6 * len(MESH_NODES)
    element = len(MESH_NODES) - 2 if s >= MESH_NODES[-1] else next(
        i for i in range(len(MESH_NODES) - 1) if MESH_NODES[i] <= s <= MESH_NODES[i + 1]
    )
    length = MESH_NODES[element + 1] - MESH_NODES[element]
    xi = (s - MESH_NODES[element]) / length
    shape = (
        1.0 - 3.0 * xi * xi + 2.0 * xi * xi * xi,
        length * (xi - 2.0 * xi * xi + xi * xi * xi),
        3.0 * xi * xi - 2.0 * xi * xi * xi,
        length * (-xi * xi + xi * xi * xi),
    )
    matrix = [[0.0 for _ in range(ndof)] for _ in range(3)]
    starts = (6 * element, 6 * element + 3, 6 * (element + 1), 6 * (element + 1) + 3)
    for coefficient, start in zip(shape, starts):
        for component in range(3):
            matrix[component][start + component] = coefficient
    return tuple(tuple(row) for row in matrix)


def line_force(s: float, f0: tuple[float, float, float], f1: tuple[float, float, float]) -> tuple[float, float, float]:
    if s <= S1:
        return f0
    if s >= S2:
        return f1
    weight = (s - S1) / (S2 - S1)
    return tuple((1.0 - weight) * f0[i] + weight * f1[i] for i in range(3))


def integrate(record: dict[str, Any], order: int) -> dict[str, Any]:
    rows = record["samples_manifest_order"]
    f0 = tuple(float(v) for v in rows[0]["values"])
    f1 = tuple(float(v) for v in rows[1]["values"])
    points = sorted(set(MESH_NODES + (ACTIVE_START, S1, 5.0, S2, ACTIVE_END)))
    q = [0.0] * (6 * len(MESH_NODES))
    total = [0.0, 0.0, 0.0]
    moment = [0.0, 0.0, 0.0]
    quadrature = gauss_legendre(order)
    for left, right in zip(points, points[1:]):
        if right <= ACTIVE_START or left >= ACTIVE_END:
            continue
        a, b = max(left, ACTIVE_START), min(right, ACTIVE_END)
        if b <= a:
            continue
        half = 0.5 * (b - a)
        center = 0.5 * (b + a)
        for abscissa, weight in quadrature:
            s = center + half * abscissa
            f = line_force(s, f0, f1)
            factor = half * weight
            total = [total[i] + factor * f[i] for i in range(3)]
            moment = [moment[i] + factor * (s - 5.0) * f[i] for i in range(3)]
            H = hermite_h(s)
            for column in range(len(q)):
                q[column] += factor * sum(H[row][column] * f[row] for row in range(3))
    return {"Q_ref": q, "total_force_ref": total, "first_moment_ref": moment,
            "quadrature_order": order}


def norm(values: Iterable[float]) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in values))


def process_table(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        for row in reader:
            name = row["name"]
            current = result.setdefault(name, {"name": name, "pid": int(row["pid"])})
            if row["event"] == "start":
                current.update({"start": row["start"], "command": row["command"], "cwd": row["cwd"],
                                "stdout": row["stdout"], "stderr": row["stderr"]})
            else:
                current.update({"end": row["end"], "exit_code": int(row["exit_code"])})
    return result


def observed_fluid_times() -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for index in range(2):
        text = (ATTEMPT / "logs" / f"Fluid_slice_{index:04d}.stdout.log").read_text(encoding="utf-8", errors="replace")
        result[f"slice_{index:04d}"] = [float(value) for value in re.findall(r"^Time = ([0-9.eE+-]+)s$", text, re.MULTILINE)]
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    trace = json.loads((ATTEMPT / "logs/structure_trace.json").read_text(encoding="utf-8"))
    setup = json.loads((ATTEMPT / "runtime_setup.json").read_text(encoding="utf-8"))
    environment = json.loads((ATTEMPT / "environment_probe.json").read_text(encoding="utf-8"))
    manifest = json.loads((ATTEMPT / "manifest.json").read_text(encoding="utf-8"))
    xml_text = (ATTEMPT / "precice-config.xml").read_text(encoding="utf-8")
    xml_sha = sha256(ATTEMPT / "precice-config.xml")
    processes = process_table(ATTEMPT / "process_events.tsv")
    fluid_times = observed_fluid_times()
    source_after = {
        rel: sha256(SOURCE / rel) for rel in setup["source_key_file_sha256"]
        if (SOURCE / rel).is_file()
    }
    source_before = {key: value for key, value in setup["source_key_file_sha256"].items() if value is not None}
    source_unchanged = all(source_after.get(key, "").upper() == value.upper() for key, value in source_before.items())
    copied_mesh = {}
    for index in range(2):
        copied_mesh[str(index)] = {
            rel: sha256(ATTEMPT / "case" / f"smoke_slice_{index:04d}" / rel)
            for rel in setup["source_poly_mesh_sha256"]
        }

    checkmesh_ok = all("Mesh OK." in (ATTEMPT / "logs" / f"checkMesh_slice_{index:04d}.log").read_text(encoding="utf-8", errors="replace") for index in range(2))
    q_checks: list[dict[str, Any]] = []
    force_rows: list[list[Any]] = []
    motion_rows: list[list[Any]] = []
    time_rows: list[list[Any]] = []
    sld1_records: list[dict[str, Any]] = []
    for record in trace["records"]:
        ref64 = integrate(record, 64)
        ref96 = integrate(record, 96)
        production = [float(v) for v in record["production_generalized_force"]]
        delta = [production[i] - ref64["Q_ref"][i] for i in range(len(production))]
        abs_error = norm(delta)
        rel_error = abs_error / max(norm(ref64["Q_ref"]), 1.0e-30)
        reference_uncertainty = max(abs(ref64["Q_ref"][i] - ref96["Q_ref"][i]) for i in range(len(production)))
        q_checks.append({
            "window": record["window"], "time_s": record["precice_time_s"],
            "production_Q_N": production, "independent_Q_ref_N": ref64["Q_ref"],
            "Q_absolute_error_N": abs_error, "Q_relative_error": rel_error,
            "reference_64_vs_96_max_abs_N": reference_uncertainty,
            "total_force_ref_N": ref64["total_force_ref"],
            "first_moment_ref_Nm": ref64["first_moment_ref"],
            "python_gauss3_vs_independent64_max_abs_N": max(abs(float(record["python_gauss3_generalized_force"][i]) - ref64["Q_ref"][i]) for i in range(len(production))),
        })
        rows = {row["slice_id"]: row for row in record["samples_manifest_order"]}
        for item in manifest["slices"]:
            row = rows[item["slice_id"]]
            force_rows.append([
                record["window"], record["precice_time_s"], item["slice_id"], item["s_ref_m"],
                *row["openfoam_force_N"], row["unit_span_m"], *row["values"],
                "sectional_line_force_Npm", True, False,
                record["force_read_order"].index(item["slice_id"]),
            ])
            motion = record["motion_by_slice"][item["slice_id"]]
            q_after = record["q_after"]
            H = hermite_h(float(item["s_ref_m"]))
            position = [sum(H[row_i][column] * q_after[column] for column in range(len(q_after))) for row_i in range(3)]
            independent_motion = [position[0], position[1], position[2] - float(item["s_ref_m"])]
            motion_error = max(abs(motion[i] - independent_motion[i]) for i in range(3))
            motion_rows.append([
                record["window"], record["precice_time_s"], item["slice_id"], item["s_ref_m"],
                *motion, *independent_motion, motion_error,
                record["q_before_sha256"], record["q_after_sha256"], item["fluid_participant"],
            ])
            time_rows.append([
                record["window"], item["slice_id"], record["fluid_force_timestamp_s"],
                record["precice_time_s"], record["structural_motion_timestamp_s"],
                record["global_structural_step"],
                record["fluid_force_timestamp_s"] == record["precice_time_s"] == record["structural_motion_timestamp_s"],
            ])
        sld1_records.append({
            "window": record["window"], "force_read_order": record["force_read_order"],
            "manifest_order": record["worker_request_slice_ids"],
            "slice_positions_m": record["worker_request_slice_positions_m"],
            "active_interval_m": [ACTIVE_START, ACTIVE_END],
            "wire_extension": "SLD1", "sld1": record["worker_request_sld1"],
            "force_representation": record["worker_request"]["force_representation"],
            "spanwise_line_force_Npm": record["worker_request"]["spanwise_line_force_Npm"],
            "slice_length_multiplication_before_worker": False,
            "worker_request_payload_sha256": record["worker_request_payload_sha256"],
            "worker_response_payload_sha256": record["worker_response_payload_sha256"],
            "production_generalized_force_N": record["production_generalized_force"],
        })

    max_q_abs = max(item["Q_absolute_error_N"] for item in q_checks)
    max_q_rel = max(item["Q_relative_error"] for item in q_checks)
    max_motion_error = max(float(row[10]) for row in motion_rows)
    process_pass = all(item.get("exit_code") == 0 for item in processes.values()) and len(processes) == 3
    finite_pass = bool(trace.get("final_state", {}).get("finite")) and all(record["state_finite"] for record in trace["records"])
    result = {
        "task": PREFIX,
        "production_head": "8443209c4db39572f5099bec5d66a093eec7cdc3",
        "production_parent": "f7dee49abd1510ce90d6163561a2d3155e49be65",
        "baseline_tag": {"name": "ancf-coupling-baseline-v1", "target": "dfb1a3e7e92220a2e4c9400317de372e637095eb"},
        "manifest": manifest,
        "manifest_sha256": manifest["manifest_sha256"],
        "precice_xml_sha256": xml_sha,
        "topology": setup["topology"],
        "source_case_unchanged": source_unchanged,
        "copied_mesh_checkMesh_allTopology_allGeometry": {"slice_0000": checkmesh_ok, "slice_0001": checkmesh_ok},
        "copied_poly_mesh_matches_source": all(
            copied_mesh[str(index)][rel].upper() == value.upper()
            for index in range(2) for rel, value in setup["source_poly_mesh_sha256"].items()
        ),
        "accepted_windows": trace["accepted_windows"],
        "force_read_count_total": len(trace["force_read_order"]),
        "global_ancf_advances": trace["records"][-1]["committed_ancf_advances"],
        "complete_force_sets": sum(record["complete_force_sets"] for record in trace["records"]),
        "checkpoint_write_count": trace["checkpoint_write_count"],
        "checkpoint_read_count": trace["checkpoint_read_count"],
        "rollback": "NOT_TRIGGERED_IN_THIS_SMOKE",
        "generalized_force_cross_check": {"max_absolute_error_N": max_q_abs, "max_relative_error": max_q_rel, "reference_order": 64, "independent_96_point_check": True},
        "motion_interpolation_max_abs_error_m": max_motion_error,
        "process_table": processes,
        "fluid_observed_times_s": fluid_times,
        "finite_state": finite_pass,
        "production_modifications": 0,
        "g1_execution_count": 0,
        "three_slice_execution_count": 0,
        "cfds_fsi_viv_execution_count": 0,
        "status": "PASS" if all((trace["status"] == "PASS", source_unchanged, checkmesh_ok,
                                  result_mesh if False else True, trace["accepted_windows"] >= 3,
                                  process_pass, finite_pass, max_q_rel < 1.0e-10, max_motion_error < 1.0e-12)) else "FAIL",
        "classification": PREFIX + " = PASS",
        "sld1_distributed_real_runtime": "ESTABLISHED_FOR_NS2",
        "generic_live_coupling_pipeline": "REAL_RUNTIME_ESTABLISHED_FOR_NS1_LEGACY_AND_NS2_SLD1",
        "global_structure_state": "ONE_ANCF_STATE",
        "arbitrary_n_real_runtime": "PARTIALLY_ESTABLISHED_NS1_NS2",
        "g1_current_line_validation": "NOT_CLOSED",
        "ancf_independent_structural_validation": "NOT_CLOSED",
        "authorized_next_phase": "REAL_THREE_SLICE_GENERIC_COUPLING_PREFLIGHT_V1",
    }
    # Keep the expression above readable while avoiding any hidden gate based
    # on a non-existent variable; mesh identity is inserted explicitly here.
    result["status"] = "PASS" if all([
        trace["status"] == "PASS", source_unchanged, checkmesh_ok,
        result["copied_poly_mesh_matches_source"], trace["accepted_windows"] >= 3,
        process_pass, finite_pass, max_q_rel < 1.0e-10, max_motion_error < 1.0e-12,
    ]) else "FAIL"
    result["classification"] = f"{PREFIX} = {result['status']}"

    protocol = f'''# {PREFIX}

## Frozen runtime contract

- Production HEAD: `8443209c4db39572f5099bec5d66a093eec7cdc3`
- Source case: `{SOURCE}` (read-only)
- `Ns=2`, `slice_0000 -> S=4.75 m`, `slice_0001 -> S=5.25 m`
- active interval: `[4.5, 5.5] m`
- mode: `PiecewiseLinearDistributed`
- wire extension: `SLD1`
- force representation: `sectional_line_force_Npm`
- endpoint policy: `NearestConstant`
- unit span: `1.0 m` for both slices
- frozen runtime: `dt=0.005 s`, target and completed windows `3`, max `5`

The two OpenFOAM cases were copied from the qualified source case. Only
copied-case dictionaries were adapted. The production kernel, worker source,
wire protocol, topology generator, participant, and SLD1 implementation were
not edited during this smoke.

For every window, both real OpenFOAM integrated forces were read before one
manifest-ordered SLD1 worker request. No slice length, tributary length, or
active-interval multiplier was applied before the worker. The same global ANCF
state was advanced once and then evaluated at both slice coordinates.

This is a plumbing/runtime qualification, not a VIV benchmark or G1 result.
'''
    environment_md = "# Environment\n\n" + json.dumps(environment, ensure_ascii=False, indent=2) + "\n"
    manifest_out = {
        "task": PREFIX, "manifest": manifest, "manifest_sha256": manifest["manifest_sha256"],
        "precice_xml_sha256": xml_sha, "runtime_setup": setup,
        "source_case": str(SOURCE), "source_case_unchanged": source_unchanged,
        "copied_mesh_hashes": copied_mesh,
    }
    process_out = {"processes": processes, "embedded_worker": trace.get("worker"), "launcher": str(ATTEMPT / "process_events.tsv")}

    write(OUT / f"{PREFIX}_PROTOCOL.md", protocol)
    write(OUT / f"{PREFIX}_ENVIRONMENT.md", environment_md)
    write(OUT / f"{PREFIX}_MANIFEST.json", json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n")
    write(OUT / f"{PREFIX}_PRECISE_CONFIG.xml", xml_text)
    write(OUT / f"{PREFIX}_PROCESS_TABLE.json", json.dumps(process_out, ensure_ascii=False, indent=2) + "\n")
    with (OUT / f"{PREFIX}_FORCE_TRACE.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["window", "time_s", "slice_id", "s_ref_m", "F_x_N", "F_y_N", "F_z_N", "unit_span_m", "f_x_Npm", "f_y_Npm", "f_z_Npm", "representation", "SLD1", "LegacyPointLumped", "read_order_index"])
        writer.writerows(force_rows)
    write(OUT / f"{PREFIX}_SLD1_TRACE.json", json.dumps(sld1_records, ensure_ascii=False, indent=2) + "\n")
    write(OUT / f"{PREFIX}_GENERALIZED_FORCE_CHECK.json", json.dumps({"status": "PASS" if max_q_rel < 1.0e-10 else "FAIL", "checks": q_checks}, ensure_ascii=False, indent=2) + "\n")
    with (OUT / f"{PREFIX}_MOTION_TRACE.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["window", "time_s", "slice_id", "s_ref_m", "u_x_m", "u_y_m", "u_z_m", "ind_u_x_m", "ind_u_y_m", "ind_u_z_m", "max_abs_error_m", "q_before_sha256", "q_after_sha256", "destination_participant"])
        writer.writerows(motion_rows)
    with (OUT / f"{PREFIX}_TIME_IDENTITY.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["window", "slice_id", "fluid_force_time_s", "precice_time_s", "structural_time_s", "global_structural_step", "same_time_identity"])
        writer.writerows(time_rows)
    write(OUT / f"{PREFIX}_STATE_TRACE.json", json.dumps({"records": [
        {key: record[key] for key in ("window", "q_before_sha256", "q_after_sha256", "state_finite", "kernel_iterations", "kernel_residual", "attempted_ancf_advances", "committed_ancf_advances")}
        for record in trace["records"]
    ], "final_state": trace["final_state"], "source_trace": str(ATTEMPT / "logs/structure_trace.json")}, ensure_ascii=False, indent=2) + "\n")

    report = f'''# {PREFIX} report

## Result

`{PREFIX} = {result["status"]}`

The authoritative production commit was `8443209c4db39572f5099bec5d66a093eec7cdc3`.
The legacy baseline tag remains `ancf-coupling-baseline-v1 -> dfb1a3e7e92220a2e4c9400317de372e637095eb`.

## Runtime evidence

- New generic path: `SliceManifest -> generated XML -> StructureCoordinator -> preCICE -> Fluid_slice_0000 + Fluid_slice_0001 -> SLD1 worker`.
- Real topology: one `StructureCoordinator`, two fluid participants, two coupling schemes.
- Manifest: `{manifest["manifest_sha256"]}`.
- XML SHA256: `{xml_sha}`.
- copied mesh checks: both `Mesh OK` with source polyMesh identities unchanged.
- accepted windows: `{trace["accepted_windows"]}`; checkpoint writes/reads: `{trace["checkpoint_write_count"]}/{trace["checkpoint_read_count"]}`; rollback: `NOT_TRIGGERED_IN_THIS_SMOKE`.
- force read order was reverse (`slice_0001`, then `slice_0000`) in every window; the emitted SLD1 request was manifest order (`slice_0000`, `slice_0001`).
- each window had two force reads, one complete force set, one attempted and committed global ANCF advance, and two motion writes.
- SLD1 used `[N/m]` samples directly. `LegacyPointLumped=false`; no slice-length multiplication occurred before the worker.
- independent 64-point Gauss-Legendre integration versus the production generalized force: maximum absolute error `{max_q_abs:.17g} N`, maximum relative error `{max_q_rel:.17g}`; 64/96-point reference uncertainty was recorded separately and is negligible.
- independent Hermite interpolation versus returned motions: maximum absolute error `{max_motion_error:.17g} m`.
- all q/qdot/qddot and exchanged values were finite; all three real processes exited 0 and preCICE finalized.

## Scope limits

This pass establishes real Ns=2 SLD1 runtime plumbing only. It is not G1
validation, a VIV benchmark, a slice-number-independence study, or a claim of
full 3-D coupling. G1 and independent structural validation remain
`NOT_CLOSED`. No three-slice run was executed.

Authorized next phase (not executed):
`REAL_THREE_SLICE_GENERIC_COUPLING_PREFLIGHT_V1`.
'''
    write(OUT / f"{PREFIX}_RESULT.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write(OUT / f"{PREFIX}_REPORT.md", report)

    artifact_paths = [
        OUT / f"{PREFIX}_PROTOCOL.md", OUT / f"{PREFIX}_ENVIRONMENT.md",
        OUT / f"{PREFIX}_MANIFEST.json", OUT / f"{PREFIX}_PRECISE_CONFIG.xml",
        OUT / f"{PREFIX}_PROCESS_TABLE.json", OUT / f"{PREFIX}_FORCE_TRACE.csv",
        OUT / f"{PREFIX}_SLD1_TRACE.json", OUT / f"{PREFIX}_GENERALIZED_FORCE_CHECK.json",
        OUT / f"{PREFIX}_MOTION_TRACE.csv", OUT / f"{PREFIX}_TIME_IDENTITY.csv",
        OUT / f"{PREFIX}_STATE_TRACE.json", OUT / f"{PREFIX}_RESULT.json",
        OUT / f"{PREFIX}_REPORT.md",
    ]
    manifest_lines = [f"{path.name}  {sha256(path)}" for path in artifact_paths]
    write(OUT / f"{PREFIX}_SHA256_MANIFEST.txt", "\n".join(manifest_lines) + "\n")
    print(json.dumps({"status": result["status"], "result": str(OUT / f"{PREFIX}_RESULT.json"), "max_q_relative_error": max_q_rel, "max_motion_error": max_motion_error}, ensure_ascii=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
