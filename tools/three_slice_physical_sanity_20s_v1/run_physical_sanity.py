#!/usr/bin/env python3
"""Fresh 20 s three-slice run retaining V2 physics, force and quality contracts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.ancf_newton_evidence_v1 import validate_records as validate_newton_records
from coupling.openfoam_numerical_quality_contract_v2 import audit_log, evaluate_quality

RUNTIME = ROOT / "runtime" / "three_slice_physical_sanity_20s_v1_run_001"
RESULTS = ROOT / "results" / "three_slice_physical_sanity_20s_v1_run_001"
CONTRACT = Path(__file__).with_name("three_slice_physical_sanity_20s_v1_contract.json")
QUALITY = ROOT / "tools" / "numerical_quality_evidence_closure_v1" / "openfoam_numerical_quality_contract_v2.json"
V1 = ROOT / "tools" / "three_slice_force_contract_smoke_v1" / "run_smoke.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("physical_sanity_base_launcher", V1)
    if spec is None or spec.loader is None: raise RuntimeError("cannot load V2-compatible launcher base")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    original_xml = module.xml
    module.RUNTIME, module.RESULTS, module.CONTRACT = RUNTIME, RESULTS, CONTRACT
    module.CONTROL = module.CONTROL.replace("endTime 1;", "endTime 20;")
    module.xml = lambda sid: original_xml(sid).replace('<max-time value="1"/>', '<max-time value="20"/>')
    return module


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file(): raise RuntimeError(f"missing required evidence: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def force_reconciliation(rows: list[dict[str, object]], sid: int) -> float:
    source = RUNTIME / "cases" / f"slice_{sid:04d}" / "postProcessing" / "cylinderForces"
    matches = list(source.glob("*/forces.dat"))
    if len(matches) != 1: return math.inf
    actual: dict[float, tuple[float, float, float]] = {}
    for line in matches[0].read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"): continue
        values = [float(v) for v in re.findall(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", line)]
        if len(values) < 7: return math.inf
        actual[round(values[0], 12)] = (values[1] + values[4], values[2] + values[5], values[3] + values[6])
    maximum = 0.0
    for row in rows:
        value = actual.get(round(float(row["time_s"]), 12))
        load = row["loads"][sid]
        if value is None: return math.inf
        maximum = max(maximum, *(abs(value[i] - float(load[key])) for i, key in enumerate(("openfoam_force_x_N", "openfoam_force_y_N", "openfoam_force_z_N"))))
    return maximum


def audit(return_code: int) -> dict[str, object]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8")); quality_contract = json.loads(QUALITY.read_text(encoding="utf-8"))
    steps, dt = int(contract["number_of_steps"]), float(contract["dt_s"])
    rows = read_jsonl(RUNTIME / "records.jsonl"); newton = read_jsonl(RUNTIME / "newton_evidence.jsonl")
    summary = json.loads((RUNTIME / "structure_summary.json").read_text(encoding="utf-8"))
    returns = {key: int(value) for key, value in (line.split("=", 1) for line in (RUNTIME / "logs" / "returns.txt").read_text(encoding="utf-8").splitlines())}
    mc = contract["mapping_contract"]; tolerance = float(mc["force_chain_identity_tolerance_N"])
    identity = True; finite = True; continuous = len(rows) == steps
    for index, row in enumerate(rows, start=1):
        continuous = continuous and int(row["global_step"]) == index and int(row["integer_tick"]) == round(index * dt * 1e9) and abs(float(row["time_s"]) - index * dt) < 1e-12
        finite = finite and bool(row.get("committed")) and len(row["loads"]) == 3 and len(row["motion"]) == 3
        for load in row["loads"]:
            for axis in "xyz":
                identity = identity and abs(float(load[f"force_2d_{axis}_Npm"]) - float(load[f"openfoam_force_{axis}_N"]) / float(load["unit_span_m"])) <= tolerance
                identity = identity and abs(float(load[f"force_{axis}_N"]) - float(load[f"force_2d_{axis}_Npm"]) * float(load["slice_length_m"])) <= tolerance
        for motion in row["motion"]:
            finite = finite and all(math.isfinite(float(motion[key])) for key in ("x_m", "y_m", "z_m", "ux_m", "uy_m", "uz_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2"))
    quality: dict[str, object] = {}
    for sid in range(3):
        parsed = audit_log(RUNTIME / "logs" / f"fluid_{sid:04d}.stdout", RUNTIME / "cases" / f"slice_{sid:04d}" / "system" / "fvSolution")
        if len(parsed["time_records"]) != steps: raise RuntimeError(f"slice {sid} raw time record count is incomplete")
        quality[str(sid)] = {"audit": parsed, "evaluation": evaluate_quality(parsed, quality_contract)}
    moments = [row["moment_audit"] for row in rows]
    max_force = max(float(x["force_error_absolute_N"]) for x in moments); max_moment = max(float(x["moment_error_absolute_Nm"]) for x in moments)
    max_v2 = max(float(x["moment_error_normalized_v2"]) for x in moments); max_work = max(float(x["virtual_work"]["normalized_error"]) for x in moments)
    reconciled = [force_reconciliation(rows, sid) for sid in range(3)]
    try: newton_summary = validate_newton_records(newton, expected_steps=steps)
    except Exception as exc: newton_summary = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
    guard = float(contract["physical_sanity_contract"]["hard_blowup_guard"]["max_abs_transverse_displacement_m"])
    max_abs_y = [max(abs(float(row["motion"][sid]["uy_m"])) for row in rows) for sid in range(3)]
    checks = {
        "all_participant_return_codes": return_code == 0 and all(value == 0 for value in returns.values()),
        "coupled_windows": len(rows) == steps and summary.get("committed_steps") == steps and continuous,
        "force_contract": identity and max(reconciled) <= float(mc["openfoam_force_function_reconciliation_tolerance_N"]),
        "mapping_contract": max_force <= float(mc["force_error_tolerance_N"]) and max_moment <= float(mc["absolute_moment_error_tolerance_Nm"]) and max_v2 <= float(mc["normalized_moment_v2_tolerance"]) and max_work <= float(mc["virtual_work_tolerance"]),
        "openfoam_quality_v2": all(item["evaluation"]["status"] == "pass" for item in quality.values()),
        "ancf_newton_evidence": newton_summary.get("status") == "pass" and len(newton) == 2 * steps,
        "finite_and_bounded": finite and all(value <= guard for value in max_abs_y),
        "no_restart_or_time_jump": continuous,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "openfoam_quality_v2.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result = {"THREE_SLICE_PHYSICAL_SANITY_20S": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "max_abs_transverse_displacement_m": max_abs_y, "force_function_reconciliation_max_N": reconciled, "max_force_error_N": max_force, "max_absolute_moment_error_Nm": max_moment, "max_v2_moment_error": max_v2, "max_virtual_work_error": max_work, "quality_contract_sha256": hashlib.sha256(QUALITY.read_bytes()).hexdigest(), "newton_evidence": newton_summary, "structure_summary": summary, "formal_status": contract["physical_sanity_contract"]["formal_status"], "next_longer_physical_run": "CONDITIONAL" if all(checks.values()) else "NOT_AUTHORIZED"}
    (RESULTS / "three_slice_physical_sanity_20s_v1_gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists(): raise RuntimeError("refusing to reuse a versioned 20 s runtime or result path")
    launcher = load_launcher(); cases = launcher.prepare(); result = audit(launcher.launch(cases))
    print(json.dumps({"gate": result["THREE_SLICE_PHYSICAL_SANITY_20S"], "results": str(RESULTS)}))
    return 0 if result["THREE_SLICE_PHYSICAL_SANITY_20S"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
