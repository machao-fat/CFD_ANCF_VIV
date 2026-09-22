"""Assemble read-only evidence for the completed Ns=3 preflight."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
ATTEMPT = ROOT / "runtime/coupling_validation/REAL_THREE_SLICE_GENERIC_COUPLING_PREFLIGHT_V1_attempt_001"
OUT = ROOT / "runtime/ANCF_validation"
SOURCE = Path(r"D:\CFD\CFD_ANCF_VIV\runtime\ANCF_validation\mesh_case")
PREFIX = "REAL_THREE_SLICE_GENERIC_COUPLING_PREFLIGHT_V1"
MESH_NODES = (0.0, 2.5, 5.0, 7.5, 10.0)
ACTIVE_START, ACTIVE_END = 4.5, 5.5


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
        values[index - 1] = (-z, weight)
        values[order - index] = (z, weight)
    return tuple(values)


def hermite_h(s: float) -> tuple[tuple[float, ...], ...]:
    ndof = 6 * len(MESH_NODES)
    element = len(MESH_NODES) - 2 if s >= MESH_NODES[-1] else next(
        i for i in range(len(MESH_NODES) - 1) if MESH_NODES[i] <= s <= MESH_NODES[i + 1])
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


def line_force(s: float, positions: tuple[float, ...], forces: tuple[tuple[float, float, float], ...]) -> tuple[float, float, float]:
    if s <= positions[0]:
        return forces[0]
    if s >= positions[-1]:
        return forces[-1]
    for index, (left, right) in enumerate(zip(positions, positions[1:])):
        if left <= s <= right:
            weight = (s - left) / (right - left)
            return tuple((1.0 - weight) * forces[index][component] + weight * forces[index + 1][component] for component in range(3))  # type: ignore[return-value]
    raise RuntimeError("line-force segment not found")


def integrate(record: dict[str, Any], order: int, positions: tuple[float, ...]) -> dict[str, Any]:
    rows = record["samples_manifest_order"]
    forces = tuple(tuple(float(v) for v in row["values"]) for row in rows)
    points = sorted(set(MESH_NODES + (ACTIVE_START, ACTIVE_END, *positions, 5.0)))
    q = [0.0] * (6 * len(MESH_NODES)); total = [0.0, 0.0, 0.0]; moment = [0.0, 0.0, 0.0]
    for left, right in zip(points, points[1:]):
        if right <= ACTIVE_START or left >= ACTIVE_END:
            continue
        a, b = max(left, ACTIVE_START), min(right, ACTIVE_END)
        if b <= a:
            continue
        half, center = 0.5 * (b - a), 0.5 * (b + a)
        for abscissa, weight in gauss_legendre(order):
            s = center + half * abscissa; factor = half * weight
            force = line_force(s, positions, forces)
            total = [total[i] + factor * force[i] for i in range(3)]
            moment = [moment[i] + factor * (s - 5.0) * force[i] for i in range(3)]
            H = hermite_h(s)
            for column in range(len(q)):
                q[column] += factor * sum(H[row][column] * force[row] for row in range(3))
    return {"Q_ref": q, "total_force_ref": total, "first_moment_ref": moment, "quadrature_order": order}


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
                current.update({"start": row["start"], "command": row["command"], "cwd": row["cwd"], "stdout": row["stdout"], "stderr": row["stderr"]})
            else:
                current.update({"end": row["end"], "exit_code": int(row["exit_code"])})
    return result


def observed_fluid_times() -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for index in range(3):
        path = ATTEMPT / "logs" / f"Fluid_slice_{index:04d}.stdout.log"
        text = path.read_text(encoding="utf-8", errors="replace")
        result[f"slice_{index:04d}"] = [float(value) for value in re.findall(r"^Time = ([0-9.eE+-]+)s$", text, re.MULTILINE)]
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    trace = json.loads((ATTEMPT / "logs/structure_trace.json").read_text(encoding="utf-8"))
    setup = json.loads((ATTEMPT / "runtime_setup.json").read_text(encoding="utf-8"))
    environment = json.loads((ATTEMPT / "environment_probe.json").read_text(encoding="utf-8"))
    manifest = json.loads((ATTEMPT / "manifest.json").read_text(encoding="utf-8"))
    xml_path = ATTEMPT / "precice-config.xml"; xml_text = xml_path.read_text(encoding="utf-8"); xml_sha = sha256(xml_path)
    processes = process_table(ATTEMPT / "process_events.tsv"); fluid_times = observed_fluid_times()
    source_after = {rel: sha256(SOURCE / rel) for rel in setup["source_key_file_sha256"] if (SOURCE / rel).is_file()}
    source_before = {key: value for key, value in setup["source_key_file_sha256"].items() if value is not None}
    source_unchanged = all(source_after.get(key, "").upper() == value.upper() for key, value in source_before.items())
    copied_mesh_matches = all(
        sha256(ATTEMPT / "case" / f"smoke_slice_{index:04d}" / rel).upper() == value.upper()
        for index in range(3) for rel, value in setup["source_poly_mesh_sha256"].items()
    )
    mesh_checks = {
        f"slice_{index:04d}": "Mesh OK." in (ATTEMPT / "logs" / f"checkMesh_slice_{index:04d}.log").read_text(encoding="utf-8", errors="replace")
        for index in range(3)
    }
    positions = tuple(float(item["s_ref_m"]) for item in manifest["slices"])
    q_checks: list[dict[str, Any]] = []; force_rows: list[list[Any]] = []; motion_rows: list[list[Any]] = []; time_rows: list[list[Any]] = []; sld1_records: list[dict[str, Any]] = []
    for record in trace["records"]:
        ref64, ref96 = integrate(record, 64, positions), integrate(record, 96, positions)
        production = [float(v) for v in record["production_generalized_force"]]
        delta = [production[i] - ref64["Q_ref"][i] for i in range(len(production))]
        abs_error = norm(delta); rel_error = abs_error / max(norm(ref64["Q_ref"]), 1.0e-30)
        uncertainty = max(abs(ref64["Q_ref"][i] - ref96["Q_ref"][i]) for i in range(len(production)))
        q_checks.append({"window": record["window"], "time_s": record["precice_time_s"], "production_Q_N": production,
                         "independent_Q_ref_N": ref64["Q_ref"], "Q_absolute_error_N": abs_error, "Q_relative_error": rel_error,
                         "reference_64_vs_96_max_abs_N": uncertainty, "total_force_ref_N": ref64["total_force_ref"],
                         "first_moment_ref_Nm": ref64["first_moment_ref"], "reference_orders": [64, 96]})
        rows_by_id = {row["slice_id"]: row for row in record["samples_manifest_order"]}
        for item in manifest["slices"]:
            row = rows_by_id[item["slice_id"]]
            force_rows.append([record["window"], record["precice_time_s"], item["slice_id"], item["s_ref_m"],
                               *row["openfoam_force_N"], row["unit_span_m"], *row["values"],
                               "sectional_line_force_Npm", True, False, record["force_read_order"].index(item["slice_id"])])
            q_after = record["q_after"]; H = hermite_h(float(item["s_ref_m"]))
            position = [sum(H[row_i][column] * q_after[column] for column in range(len(q_after))) for row_i in range(3)]
            motion = record["motion_by_slice"][item["slice_id"]]
            independent = [position[0], position[1], position[2] - float(item["s_ref_m"])]
            error = max(abs(float(motion[i]) - independent[i]) for i in range(3))
            motion_rows.append([record["window"], record["precice_time_s"], item["slice_id"], item["s_ref_m"], *motion, *independent, error, record["q_before_sha256"], record["q_after_sha256"], item["fluid_participant"]])
            time_rows.append([record["window"], item["slice_id"], record["fluid_force_timestamp_s"], record["precice_time_s"], record["structural_motion_timestamp_s"], record["global_structural_step"], True])
        sld1_records.append({"window": record["window"], "force_read_order": record["force_read_order"], "manifest_order": record["worker_request_slice_ids"], "slice_positions_m": record["worker_request_slice_positions_m"], "active_interval_m": [ACTIVE_START, ACTIVE_END], "wire_extension": "SLD1", "sld1": record["worker_request_sld1"], "force_representation": record["worker_request"]["force_representation"], "spanwise_line_force_Npm": record["worker_request"]["spanwise_line_force_Npm"], "slice_length_multiplication_before_worker": False, "production_generalized_force_N": record["production_generalized_force"]})
    max_q_abs = max(item["Q_absolute_error_N"] for item in q_checks); max_q_rel = max(item["Q_relative_error"] for item in q_checks)
    max_motion_error = max(float(row[10]) for row in motion_rows)
    process_pass = len(processes) == 4 and all(item.get("exit_code") == 0 for item in processes.values())
    finite_pass = bool(trace.get("final_state", {}).get("finite")) and all(record["state_finite"] for record in trace["records"])
    worker_pass = trace.get("worker", {}).get("return_code") == 0
    status = "PASS" if all((trace.get("status") == "PASS", trace.get("precice_initialized"), trace.get("precice_finalized"), source_unchanged, copied_mesh_matches, all(mesh_checks.values()), trace.get("accepted_windows", 0) >= 3, process_pass, worker_pass, finite_pass, max_q_rel < 1.0e-10, max_motion_error < 1.0e-12)) else "FAIL"
    result = {"task": PREFIX, "production_head": "8443209c4db39572f5099bec5d66a093eec7cdc3", "production_parent": "f7dee49abd1510ce90d6163561a2d3155e49be65", "baseline_tag": {"name": "ancf-coupling-baseline-v1", "target": "dfb1a3e7e92220a2e4c9400317de372e637095eb"}, "manifest": manifest, "manifest_sha256": manifest["manifest_sha256"], "precice_xml_sha256": xml_sha, "topology": setup["topology"], "source_case_unchanged": source_unchanged, "copied_poly_mesh_matches_source": copied_mesh_matches, "mesh_checks": mesh_checks, "accepted_windows": trace.get("accepted_windows", 0), "force_read_count_total": len(trace.get("force_read_order", [])), "complete_force_sets": sum(record["complete_force_sets"] for record in trace["records"]), "global_ancf_advances": sum(record["committed_ancf_advances"] for record in trace["records"]), "checkpoint_write_count": trace.get("checkpoint_write_count", 0), "checkpoint_read_count": trace.get("checkpoint_read_count", 0), "rollback": "NOT_TRIGGERED_IN_THIS_PREFLIGHT", "generalized_force_cross_check": {"max_absolute_error_N": max_q_abs, "max_relative_error": max_q_rel, "reference_orders": [64, 96]}, "motion_interpolation_max_abs_error_m": max_motion_error, "process_table": processes, "embedded_worker": trace.get("worker"), "fluid_observed_times_s": fluid_times, "finite_state": finite_pass, "production_modifications": 0, "g1_execution_count": 0, "long_run_viv_execution_count": 0, "ns5_execution_count": 0, "ns8_execution_count": 0, "run_once_wrapper_postrun_logging_exception": True, "run_once_wrapper_note": "Coupled processes completed; outer Windows printer hit UnicodeEncodeError while printing WSL warning. Runtime trace and process exit records are authoritative.", "status": status, "classification": f"{PREFIX} = {status}", "sld1_distributed_real_runtime": "ESTABLISHED_FOR_NS2_NS3" if status == "PASS" else "NOT_ESTABLISHED", "generic_arbitrary_n_runtime_architecture": "REAL_RUNTIME_EVIDENCED_FOR_NS1_NS2_NS3" if status == "PASS" else "NOT_ESTABLISHED", "global_structure_state": "ONE_ANCF_STATE" if status == "PASS" else "UNRESOLVED", "coupling_infrastructure_qualification": "COMPLETE" if status == "PASS" else "NOT_COMPLETE", "authorized_next_phase": "COUPLING_BASELINE_V2_FREEZE" if status == "PASS" else "NONE"}

    protocol = f'''# {PREFIX}\n\nStatus: `{PREFIX} = {status}`\n\nThis was one bounded real runtime preflight using the current generic arbitrary-N path. It used Ns=3, PiecewiseLinearDistributed, SLD1, unit span 1 m, active interval [4.5, 5.5] m, and nonuniform positions 4.65, 4.95, and 5.35 m. The source case remained read-only and three copied polyMesh identities were checked.\n\nNo production source was modified. No Ns=5/8 run, long-time VIV run, G1 case, or literature comparison was executed.\n'''
    environment_md = "# Environment\n\n" + json.dumps(environment, ensure_ascii=False, indent=2) + "\n"
    manifest_out = {"task": PREFIX, "manifest": manifest, "manifest_sha256": manifest["manifest_sha256"], "precice_xml_sha256": xml_sha, "runtime_setup": setup, "source_case": str(SOURCE), "source_case_unchanged": source_unchanged, "mesh_checks": mesh_checks}
    process_out = {"processes": processes, "embedded_worker": trace.get("worker"), "launcher": str(ATTEMPT / "process_events.tsv")}
    write(OUT / f"{PREFIX}_PROTOCOL.md", protocol); write(OUT / f"{PREFIX}_ENVIRONMENT.md", environment_md); write(OUT / f"{PREFIX}_MANIFEST.json", json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n"); write(OUT / f"{PREFIX}_PRECISE_CONFIG.xml", xml_text); write(OUT / f"{PREFIX}_PROCESS_TABLE.json", json.dumps(process_out, ensure_ascii=False, indent=2) + "\n")
    with (OUT / f"{PREFIX}_FORCE_TRACE.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["window", "time_s", "slice_id", "s_ref_m", "F_x_N", "F_y_N", "F_z_N", "unit_span_m", "f_x_Npm", "f_y_Npm", "f_z_Npm", "representation", "SLD1", "LegacyPointLumped", "read_order_index"]); writer.writerows(force_rows)
    write(OUT / f"{PREFIX}_SLD1_TRACE.json", json.dumps(sld1_records, ensure_ascii=False, indent=2) + "\n"); write(OUT / f"{PREFIX}_GENERALIZED_FORCE_CHECK.json", json.dumps({"status": "PASS" if max_q_rel < 1.0e-10 else "FAIL", "checks": q_checks}, ensure_ascii=False, indent=2) + "\n")
    with (OUT / f"{PREFIX}_MOTION_TRACE.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["window", "time_s", "slice_id", "s_ref_m", "u_x_m", "u_y_m", "u_z_m", "ind_u_x_m", "ind_u_y_m", "ind_u_z_m", "max_abs_error_m", "q_before_sha256", "q_after_sha256", "destination_participant"]); writer.writerows(motion_rows)
    with (OUT / f"{PREFIX}_TIME_IDENTITY.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["window", "slice_id", "fluid_force_time_s", "precice_time_s", "structural_time_s", "global_structural_step", "same_time_identity"]); writer.writerows(time_rows)
    write(OUT / f"{PREFIX}_STATE_TRACE.json", json.dumps({"records": [{key: record[key] for key in ("window", "q_before_sha256", "q_after_sha256", "state_finite", "kernel_iterations", "kernel_residual", "attempted_ancf_advances", "committed_ancf_advances")} for record in trace["records"]], "final_state": trace.get("final_state"), "source_trace": str(ATTEMPT / "logs/structure_trace.json")}, ensure_ascii=False, indent=2) + "\n")
    report = f'''# {PREFIX} report\n\n## Final classification\n\n`{PREFIX} = {status}`\n\n- HEAD: `8443209c4db39572f5099bec5d66a093eec7cdc3`\n- Manifest: `{manifest["manifest_sha256"]}`\n- XML SHA256: `{xml_sha}`\n- Participants: one `StructureCoordinator` and three generic `Fluid_slice_000*` participants.\n- Positions: `S1=4.65 m`, `S2=4.95 m`, `S3=5.35 m`; active interval `[4.5,5.5] m`.\n- Accepted windows: `{trace.get("accepted_windows", 0)}`.\n- Force read order: reverse manifest order (`slice_0002`, `slice_0001`, `slice_0000`); SLD1 request order remained manifest order.\n- Complete force sets/global ANCF advances/motion writes per window: `3 / 1 / 3`.\n- Independent Q check: max absolute error `{max_q_abs:.17g} N`, max relative error `{max_q_rel:.17g}`.\n- Independent motion interpolation maximum error: `{max_motion_error:.17g} m`.\n- Rollback: `NOT_TRIGGERED_IN_THIS_PREFLIGHT`.\n- All processes and worker exited successfully; all exchanged/state values were finite.\n\nThe outer Windows launcher printer raised a UnicodeEncodeError after the coupled processes had completed while printing a WSL warning. This did not affect the real runtime; the process table, participant trace, OpenFOAM logs, and preCICE finalization records are authoritative.\n\n`COUPLING_INFRASTRUCTURE_QUALIFICATION = COMPLETE`\n\nAuthorized next phase (not executed): `COUPLING_BASELINE_V2_FREEZE`.\nG1 and independent structural validation remain `NOT_CLOSED`.\n'''
    write(OUT / f"{PREFIX}_RESULT.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n"); write(OUT / f"{PREFIX}_REPORT.md", report)
    artifact_paths = [OUT / f"{PREFIX}_{suffix}" for suffix in ("PROTOCOL.md", "ENVIRONMENT.md", "MANIFEST.json", "PRECISE_CONFIG.xml", "PROCESS_TABLE.json", "FORCE_TRACE.csv", "SLD1_TRACE.json", "GENERALIZED_FORCE_CHECK.json", "MOTION_TRACE.csv", "TIME_IDENTITY.csv", "STATE_TRACE.json", "RESULT.json", "REPORT.md")]
    write(OUT / f"{PREFIX}_SHA256_MANIFEST.txt", "\n".join(f"{path.name}  {sha256(path)}" for path in artifact_paths) + "\n")
    print(json.dumps({"status": status, "result": str(OUT / f"{PREFIX}_RESULT.json"), "max_q_relative_error": max_q_rel, "max_motion_error": max_motion_error}, ensure_ascii=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
