"""Fresh, bounded 0.1 s coupled micro-smoke; never launches a longer run."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.ancf_newton_evidence_v1 import validate_records  # noqa: E402
from coupling.moving_mesh_patch_compatibility_v1.audit import audit as patch_audit  # noqa: E402
from coupling.openfoam_numerical_quality_contract_v2 import audit_log, evaluate_quality  # noqa: E402
from coupling.slice_independence_audit_v1.audit import parse_forces, sha256  # noqa: E402

HERE = Path(__file__).parent
CONTRACT = HERE / "generalized_force_metric_v2_and_0p1s_micro_smoke_v1_contract.json"
CONTRACT_VALUE = json.loads(CONTRACT.read_text(encoding="utf-8"))
RUNTIME = ROOT / "runtime" / CONTRACT_VALUE["run_id"]
RESULTS = ROOT / "results" / CONTRACT_VALUE["run_id"]
BASE = ROOT / "tools/corrected_moving_mesh_coupling_revalidation_v1/run_revalidation.py"
QUALITY = ROOT / "tools/numerical_quality_evidence_closure_v1/openfoam_numerical_quality_contract_v2.json"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def vec_norm(value: list[float]) -> float:
    return math.sqrt(sum(x * x for x in value))


def mesh_evidence(base, cases: list[Path], rows: list[dict]) -> tuple[list[dict], bool]:
    reference = [0.0, 0.0, 0.5]
    tol = float(CONTRACT_VALUE["moving_mesh_patch_contract"]["mesh_tracking_tolerance_m"])
    evidence: list[dict] = []; passed = True
    for time_s in CONTRACT_VALUE["micro_smoke_evidence"]["mesh_snapshot_times_s"]:
        token = "constant" if time_s == 0.0 else f"{time_s:g}"
        step = int(round(time_s / float(CONTRACT_VALUE["dt_s"])))
        for sid, case in enumerate(cases):
            try:
                actual = base.mesh_centroid(case, token)
                if time_s == 0.0:
                    displacement = [0.0, 0.0, 0.0]; point = [0.0, 0.0, 0.0]
                else:
                    # In the explicit scheme, a Fluid time directory at t stores
                    # the displacement received from the preceding completed
                    # structure window. The mesh is 2-D, so z is not transported.
                    source_step = step - 1
                    motion = rows[source_step - 1]["motion"][sid]
                    displacement = [float(motion["ux_m"]), float(motion["uy_m"]), 0.0]
                    point = base.point_centroid(case, token)
                expected = [reference[i] + displacement[i] for i in range(3)]
                err = vec_norm([actual[i] - expected[i] for i in range(3)])
                point_err = vec_norm([point[i] - displacement[i] for i in range(3)])
                passed = passed and err <= tol and point_err <= tol
                points = case / token / "polyMesh/points"
                evidence.append({"slice_id": sid, "time_s": time_s, "global_step": step,
                                 "structure_displacement_xyz_m": displacement,
                                 "structure_source_global_step": 0 if time_s == 0.0 else step - 1,
                                 "received_precice_displacement_xyz_m": point,
                                 "cylinder_pointDisplacement_xyz_m": point,
                                 "actual_cylinder_centroid_xyz_m": actual,
                                 "expected_cylinder_centroid_xyz_m": expected,
                                 "mesh_motion_error_m": err, "point_displacement_error_m": point_err,
                                 "mesh_points_sha256": sha256(points)})
            except Exception as exc:
                passed = False
                evidence.append({"slice_id": sid, "time_s": time_s, "global_step": step,
                                 "status": "missing_or_unreadable", "error": f"{type(exc).__name__}: {exc}"})
    return evidence, passed


def main() -> int:
    audit_existing = "--audit-existing" in sys.argv[1:]
    if (RUNTIME.exists() or RESULTS.exists()) and not audit_existing:
        raise RuntimeError("refusing to reuse versioned micro-smoke paths")
    base = load(BASE, "corrected_revalidation_micro")
    if audit_existing:
        cases = [RUNTIME / "cases" / f"slice_{sid:04d}" for sid in range(3)]
        returns = (RUNTIME / "logs/returns.txt").read_text(encoding="utf-8", errors="replace")
        code = 0 if all(int(value) == 0 for value in re.findall(r"=(\d+)", returns)) else 1
    else:
        launcher = base.load_launcher(RUNTIME, RESULTS, CONTRACT, 0.1)
        # Preserve pressure/viscous/total forces.dat decomposition at every
        # startup window.  Sparse function-object output made the first force
        # exchange non-auditable in run_001.
        launcher.CONTROL = launcher.CONTROL.replace("writeInterval 20;", "writeInterval 1;")
        cases = launcher.prepare()
        preflight = {str(sid): patch_audit(case) for sid, case in enumerate(cases)}
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "mesh_field_patch_compatibility_preflight.json").write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not all(x["MESH_FIELD_PATCH_COMPATIBILITY"] == "PASS" for x in preflight.values()):
            (RESULTS / "gate.json").write_text(json.dumps({"gate": "FAIL", "blocker": "MESH_FIELD_PATCH_COMPATIBILITY", "preflight": preflight}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 1
        (RESULTS / "openfoam_construction_preflight.json").write_text(json.dumps({"status": "PASS", "method": "generated moving-field and polyMesh compatibility audit", "slices": preflight, "no_physical_time_advanced": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        code = launcher.launch(cases)
    summary_path = RUNTIME / "structure_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    rows = [json.loads(x) for x in (RUNTIME / "records.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "records.jsonl").exists() else []
    attempts = [json.loads(x) for x in (RUNTIME / "correction_attempts.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "correction_attempts.jsonl").exists() else []
    newton = [json.loads(x) for x in (RUNTIME / "newton_evidence.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "newton_evidence.jsonl").exists() else []
    qcontract = json.loads(QUALITY.read_text(encoding="utf-8")); quality = {}
    for sid, case in enumerate(cases):
        quality[str(sid)] = evaluate_quality(audit_log(RUNTIME / "logs" / f"fluid_{sid:04d}.stdout", case / "system/fvSolution"), qcontract)
    try:
        newton_result = validate_records(newton, expected_steps=20)
    except Exception as exc:
        newton_result = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
    snapshots: list[dict] = []; moving_mesh = False
    try:
        snapshots, moving_mesh = mesh_evidence(base, cases, rows)
    except Exception as exc:
        snapshots = [{"error": f"{type(exc).__name__}: {exc}"}]
    moments = [row["moment_audit"] for row in rows]
    forcechain = all(abs(float(load[f"force_{axis}_N"]) - float(load[f"force_2d_{axis}_Npm"]) * float(load["slice_length_m"])) <= 1e-12
                     for row in rows for load in row.get("loads", []) for axis in "xyz")
    mapping = bool(moments) and max(float(x["force_error_absolute_N"]) for x in moments) <= 1e-8 and max(float(x["moment_error_absolute_Nm"]) for x in moments) <= 1e-7 and max(float(x["moment_error_normalized_v2"]) for x in moments) <= 1e-12 and max(float(x["virtual_work"]["normalized_error"]) for x in moments) <= 1e-12
    v2 = [item.get("generalized_force_mapping_v2", {}) for item in attempts]
    required_v2 = {"Q_formal_N", "Q_cpp_cfd_N", "Q_cpp_total_N", "H_by_slice", "cpp_request_payload_sha256", "cpp_response_payload_sha256", "generalized_force_mapping_v2"}
    persistence = len(attempts) == 20 and all(required_v2 <= set(item) and item["generalized_force_mapping_v2"].get("GENERALIZED_FORCE_MAPPING_V2") == "PASS" for item in attempts)
    force_paths = [case / "postProcessing/cylinderForces/0/forces.dat" for case in cases]
    raw_hashes = [sha256(path) for path in force_paths if path.exists()]
    raw_identical = len(raw_hashes) == 3 and len(set(raw_hashes)) == 1
    fields = {}
    for time_s in (0.05, 0.1):
        token = f"{time_s:g}"
        try:
            us = [base.arr(case / token / "U", True) for case in cases]; ps = [base.arr(case / token / "p", False) for case in cases]
            fields[token] = {"U_l2_0_1": base.l2(us[0], us[1]), "U_l2_0_2": base.l2(us[0], us[2]), "p_l2_0_1": base.l2(ps[0], ps[1]), "p_l2_0_2": base.l2(ps[0], ps[2]), "U_sha256": [sha256(case / token / "U") for case in cases], "p_sha256": [sha256(case / token / "p") for case in cases]}
        except Exception as exc:
            fields[token] = {"status": "missing_or_unreadable", "error": f"{type(exc).__name__}: {exc}"}
    courant_raw = {}
    for sid in range(3):
        text = (RUNTIME / "logs" / f"fluid_{sid:04d}.stdout").read_text(encoding="utf-8", errors="replace")
        values = [{"mean": float(a), "max": float(b)} for a, b in re.findall(r"Courant Number mean:\s*([-+0-9.eE]+) max:\s*([-+0-9.eE]+)", text)]
        courant_raw[str(sid)] = values
    max_co = max((item["max"] for values in courant_raw.values() for item in values), default=float("nan"))
    commanded = [[abs(float(row["motion"][sid]["uy_m"]) - (float(rows[index - 1]["motion"][sid]["uy_m"]) if index else 0.0)) for index, row in enumerate(rows)] for sid in range(3)]
    checks = {"launch_return": code == 0, "committed_20": len(rows) == 20 and summary.get("committed_steps") == 20,
              "force_contract": forcechain, "mapping_conservation": mapping, "generalized_force_v2": persistence,
              "newton": newton_result.get("status") == "pass" and len(newton) == 40,
              "moving_mesh_tracking": moving_mesh,
              "numerical_quality_v2": all(item.get("status") == "pass" for item in quality.values()),
              "finite": all(math.isfinite(float(row["motion"][sid]["uy_m"])) for row in rows for sid in range(3))}
    status = "PASS" if all(checks.values()) else "FAIL"
    result = {"CORRECTED_MOVING_MESH_0P1S_SMOKE": status, "checks": checks, "committed_windows": len(rows),
              "structure_summary": summary, "generalized_force_v2_attempts": v2, "attempt_count": len(attempts),
              "failed_attempt_evidence_policy": "attempt is fsync-persisted before V2 gate; this run had no failed correction" if persistence else "incomplete",
              "mesh_tracking": snapshots, "max_mesh_tracking_error_m": max((float(x.get("mesh_motion_error_m", math.inf)) for x in snapshots), default=math.inf),
              "quality_v2": quality, "max_courant": max_co, "commanded_point_displacement_increment_m": {str(i): max(v, default=0.0) for i, v in enumerate(commanded)},
              "courant_raw_log_records": courant_raw,
              "raw_force_sha256": raw_hashes, "raw_forces_byte_identical": raw_identical, "field_evidence": fields,
              "secondary_courant_risk": "present" if math.isfinite(max_co) and max_co > 0.5 else "not_observed"}
    (RESULTS / "gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": status, "windows": len(rows), "max_courant": max_co}))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
