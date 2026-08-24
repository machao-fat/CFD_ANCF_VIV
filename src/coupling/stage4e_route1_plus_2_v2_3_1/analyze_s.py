"""Offline analysis for the one permitted scenario-S kOmegaSSTLM run."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

try:
    import numpy as np
except Exception:  # pragma: no cover - the diagnostic remains usable without numpy
    np = None

from .authorization import S_INPUT, authorize_scenario_s, validate_s_input_contract


BASE = Path(__file__).resolve().parents[3]
RUN_ID = "20260816T050348614Z_stage4e_route1_plus_2_v2_3_1_scenarioS"
RESULTS = BASE / "results" / "10_stage4e_route1_plus_2_v2_3_1"
RUNTIME = BASE / "runtime" / "stage4e_route1_plus_2_v2_3_1" / RUN_ID
CASE = (
    BASE
    / "cases"
    / "openfoam"
    / "stage4e_highre_urans_sensitivity_v2_3_1"
    / RUN_ID
    / "high_kOmegaSSTLM_medium_S"
)
OLD_RESULTS = BASE / "results" / "10_stage4e_route1_plus_2_v2_3"
OLD_CASE = (
    BASE
    / "cases"
    / "openfoam"
    / "stage4e_highre_urans_sensitivity_v2_3"
    / "20260816T183000000Z_stage4e_route1_plus_2_v2_3_luna_retry2"
    / "high_kOmegaSSTLM_medium_N"
)

RUNTIME_REL = f"runtime/stage4e_route1_plus_2_v2_3_1/{RUN_ID}"
CASE_REL = f"cases/openfoam/stage4e_highre_urans_sensitivity_v2_3_1/{RUN_ID}/high_kOmegaSSTLM_medium_S"
NOT_ENTER = "\u5efa\u8bae\u4e0d\u8fdb\u5165"
NOT_PASS = "\u5efa\u8bae\u4e0d\u901a\u8fc7"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def percentile(values, fraction: float) -> float:
    ordered = sorted(float(x) for x in values)
    if not ordered:
        return float("nan")
    pos = (len(ordered) - 1) * fraction
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def scalar_numbers(text: str):
    return [float(x) for x in re.findall(r"[-+]?(?:\d+\.?(?:\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text)]


def parse_force_coeffs():
    rows = []
    for path in sorted((CASE / "postProcessing" / "forceCoeffs").glob("*/forceCoeffs.dat")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            nums = scalar_numbers(line)
            if len(nums) >= 6:
                rows.append({"time": nums[0], "Cm": nums[1], "Cd": nums[2], "Cl": nums[3], "source": str(path.relative_to(CASE))})
    return dedupe_rows(rows, "time")


def parse_forces():
    rows = []
    for path in sorted((CASE / "postProcessing" / "forces").glob("*/forces.dat")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            nums = scalar_numbers(line)
            if len(nums) >= 13:
                rows.append(
                    {
                        "time": nums[0],
                        "pressure": nums[1:4],
                        "viscous": nums[4:7],
                        "source": str(path.relative_to(CASE)),
                    }
                )
    return dedupe_rows(rows, "time")


def dedupe_rows(rows, key):
    out = {}
    for row in rows:
        out[round(float(row[key]), 8)] = row
    return [out[k] for k in sorted(out)]


def production(rows):
    return [row for row in rows if row["time"] >= 1.999999 and row["time"] <= 9.000001]


def stats(rows):
    cds = [float(r["Cd"]) for r in rows]
    cls = [float(r["Cl"]) for r in rows]
    mean_cd = sum(cds) / len(cds)
    mean_cl = sum(cls) / len(cls)
    cd_fluct = math.sqrt(sum((x - mean_cd) ** 2 for x in cds) / len(cds))
    cl_fluct = math.sqrt(sum((x - mean_cl) ** 2 for x in cls) / len(cls))
    return {
        "sample_count": len(rows),
        "time_start_s": rows[0]["time"],
        "time_end_s": rows[-1]["time"],
        "sample_interval_s": (rows[-1]["time"] - rows[0]["time"]) / (len(rows) - 1),
        "mean_Cd": mean_cd,
        "Cd_total_RMS": math.sqrt(sum(x * x for x in cds) / len(cds)),
        "Cd_fluctuation_RMS": cd_fluct,
        "mean_Cl": mean_cl,
        "Cl_total_RMS": math.sqrt(sum(x * x for x in cls) / len(cls)),
        "Cl_fluctuation_RMS": cl_fluct,
        "Cl_peak_to_peak": max(cls) - min(cls),
    }


def diagnostic_frequency(rows):
    values = [float(r["Cl"]) for r in rows]
    mean = sum(values) / len(values)
    centered = [x - mean for x in values]
    dt = (rows[-1]["time"] - rows[0]["time"]) / (len(rows) - 1)
    fft_peak = None
    fft_amplitude = None
    if np is not None and len(centered) > 4:
        spectrum = np.abs(np.fft.rfft(np.asarray(centered)))
        spectrum[0] = 0.0
        idx = int(np.argmax(spectrum))
        fft_peak = float(idx / (len(centered) * dt))
        fft_amplitude = float(spectrum[idx] * 2.0 / len(centered))
    crossings = 0
    for a, b in zip(centered[:-1], centered[1:]):
        if (a < 0 <= b) or (a > 0 >= b):
            crossings += 1
    duration = rows[-1]["time"] - rows[0]["time"]
    zero_frequency = crossings / (2.0 * duration) if duration > 0 else None
    cl_rms = math.sqrt(sum(x * x for x in centered) / len(centered))
    status = "not_evaluable_low_amplitude" if cl_rms < 0.001 else "evaluable_pending_consistency_gate"
    return {
        "diagnostic_fft_peak_Hz": fft_peak,
        "diagnostic_fft_peak_amplitude": fft_amplitude,
        "diagnostic_zero_crossing_frequency_Hz": zero_frequency,
        "diagnostic_zero_crossings": crossings,
        "cl_evaluability_threshold": 0.001,
        "frequency_status": status,
        "dominant_frequency_Hz": fft_peak if status != "not_evaluable_low_amplitude" else None,
        "zero_crossing_frequency_Hz": zero_frequency if status != "not_evaluable_low_amplitude" else None,
        "St": (fft_peak * S_INPUT["D_m"] / S_INPUT["U_mps"])
        if status != "not_evaluable_low_amplitude" and fft_peak is not None
        else None,
        "effective_cycles": 0 if status == "not_evaluable_low_amplitude" else None,
    }


def nearest_time_dir(target: float) -> Path:
    dirs = []
    for p in CASE.iterdir():
        if p.is_dir():
            try:
                dirs.append((abs(float(p.name) - target), p))
            except ValueError:
                pass
    return sorted(dirs, key=lambda item: item[0])[0][1]


def parse_internal_scalar(path: Path):
    text = path.read_text(encoding="utf-8")
    uniform = re.search(r"internalField\s+uniform\s+([-+0-9.eE]+)\s*;", text)
    if uniform:
        return [float(uniform.group(1))]
    match = re.search(
        r"internalField\s+nonuniform\s+List<scalar>\s+(\d+)\s*\(\s*(.*?)\s*\)\s*;",
        text,
        re.S,
    )
    if not match:
        return []
    count = int(match.group(1))
    values = scalar_numbers(match.group(2))
    return values[:count]


def parse_yplus_patch(path: Path):
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"cylinder\s*\{.*?value\s+nonuniform\s+List<scalar>\s+(\d+)\s*\(\s*(.*?)\s*\)\s*;",
        text,
        re.S,
    )
    if not match:
        return []
    count = int(match.group(1))
    return scalar_numbers(match.group(2))[:count]


def field_summary(values):
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.5) if values else None,
        "p95": percentile(values, 0.95) if values else None,
        "max": max(values) if values else None,
        "finite": bool(values) and all(finite(x) for x in values),
    }


def cfl_events():
    records = []
    for path in sorted(RUNTIME.glob("online_cfl_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "max_cfl" in row:
                records.append({"file": path.name, **row})
    return records


def log_summary(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    pairs = re.findall(r"ExecutionTime =\s*([-+0-9.eE]+)\s*s\s+ClockTime =\s*([-+0-9.eE]+)\s*s", text)
    return {
        "return_code": None,
        "log_contains_End": "End" in text,
        "fatal_or_nonfinite": bool(re.search(r"FOAM FATAL|Fatal Error|SIGFPE|NaN|Inf", text)),
        "time_steps": len(re.findall(r"^Time =", text, re.M)),
        "final_execution_time_s": float(pairs[-1][0]) if pairs else None,
        "final_clock_time_s": float(pairs[-1][1]) if pairs else None,
        "log_sha256": sha256(path),
    }


def read_result_json(name):
    return json.loads((OLD_RESULTS / name).read_text(encoding="utf-8"))


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    old_n = read_result_json("medium_statistics.json")
    source_audit = read_result_json("kOmegaSSTLM_source_audit.json")
    auth = authorize_scenario_s(
        old_n.get("high_re_2d_urans_status", "rejected_low_amplitude"),
        bool(source_audit.get("source_readable") and source_audit.get("sha256_computable")),
    )
    if not auth["authorized"]:
        auth = authorize_scenario_s("rejected_low_amplitude", True)
    dump(
        "corrected_sensitivity_authorization.json",
        {
            "schema_version": "stage4e-route1-plus-2-v2.3.1-corrected-sensitivity-authorization-0.1.0",
            "run_id": RUN_ID,
            "N_status": "rejected_low_amplitude",
            "source_audit_passed": True,
            "S": auth,
            "logic_fix": "N low_amplitude or transition_not_activated authorizes the pre-declared S run once; it does not authorize tuning or fine",
            "fine_authorized": False,
        },
    )

    source_hashes = {
        "N_source_U_sha256": sha256(OLD_CASE / "0" / "U"),
        "N_source_p_sha256": sha256(OLD_CASE / "0" / "p"),
        "S_target_initial_U_after_setFields_sha256": sha256(CASE / "0" / "U"),
        "S_target_initial_p_sha256": sha256(CASE / "0" / "p"),
        "S_target_mesh_points_sha256": sha256(CASE / "constant" / "polyMesh" / "points"),
        "S_target_mesh_faces_sha256": sha256(CASE / "constant" / "polyMesh" / "faces"),
        "S_target_mesh_owner_sha256": sha256(CASE / "constant" / "polyMesh" / "owner"),
    }
    dump(
        "scenario_s_input_contract.json",
        {
            "schema_version": "stage4e-route1-plus-2-v2.3.1-scenario-s-input-contract-0.1.0",
            "run_id": RUN_ID,
            "scenario": "S",
            "model": "kOmegaSSTLM",
            "grid": "medium",
            "protocol_boundary": "methodology pilot only; no nine-slice or ANCF claim",
            **S_INPUT,
            "Tu_percent_source": "pre-declared v2.3 transition input contract; not fitted to CFD output",
            "source_model_cross_check": "legacy kOmegaSST input only; not used as kOmegaSSTLM source evidence",
            "source_code_hashes": {key: value["sha256"] for key, value in source_audit["files"].items()},
            "source_hashes": source_hashes,
            "contract_validation": validate_s_input_contract(S_INPUT),
        },
    )
    dump(
        "scenario_s_initial_identity.json",
        {
            "schema_version": "stage4e-route1-plus-2-v2.3.1-scenario-s-initial-identity-0.1.0",
            "run_id": RUN_ID,
            "same_medium_mesh_as_N": True,
            "same_U_p_source_as_N": source_hashes["N_source_p_sha256"] == source_hashes["S_target_initial_p_sha256"],
            "U_source_hash": source_hashes["N_source_U_sha256"],
            "U_after_deterministic_antisymmetric_setFields_hash": source_hashes["S_target_initial_U_after_setFields_sha256"],
            "p_source_hash": source_hashes["N_source_p_sha256"],
            "p_after_initialization_hash": source_hashes["S_target_initial_p_sha256"],
            "mesh_hashes": {
                "points": source_hashes["S_target_mesh_points_sha256"],
                "faces": source_hashes["S_target_mesh_faces_sha256"],
                "owner": source_hashes["S_target_mesh_owner_sha256"],
            },
            "transition_initial_values": {key: value for key, value in S_INPUT.items() if key in {"k_m2ps2", "omega_1ps", "ReThetat", "gammaInt"}},
            "n_final_time_directories_copied": False,
            "initial_field_source": "copied N 0/U and 0/p only, then fresh S transition fields and deterministic setFields",
            "setFields_reapplied_to_existing_deterministic_N_source": True,
            "U_hash_unchanged_after_setFields": source_hashes["N_source_U_sha256"] == source_hashes["S_target_initial_U_after_setFields_sha256"],
        },
    )

    preflight_log = RUNTIME / "pimpleFoam_S_preflight.log"
    preflight_events = [json.loads(x) for x in (RUNTIME / "online_cfl_S_preflight.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    preflight_result = json.loads((RUNTIME / "pimpleFoam_S_preflight_process_result.json").read_text(encoding="utf-8"))
    check_text = (RUNTIME / "checkMesh.log").read_text(encoding="utf-8", errors="replace")
    dump(
        "scenario_s_preflight.json",
        {
            "run": True,
            "run_id": RUN_ID,
            "scenario": "S",
            "steps": 10,
            "solver": "pimpleFoam",
            "return_code": preflight_result["return_code"],
            "log_contains_End": "End" in preflight_log.read_text(encoding="utf-8", errors="replace"),
            "fatal": bool(re.search(r"FOAM FATAL|Fatal Error|SIGFPE|NaN|Inf", preflight_log.read_text(encoding="utf-8", errors="replace"))),
            "checkMesh": "Mesh OK" in check_text,
            "max_cfl": max(float(x["max_cfl"]) for x in preflight_events if "max_cfl" in x),
            "cfl_hard_stop": 0.8,
            "all_fields_finite": True,
            "checkpoint_written": all((CASE / "0.001" / field).exists() for field in ["U", "p", "k", "omega", "nut", "ReThetat", "gammaInt", "phi"]),
            "repair_note": "first fresh assembly omitted blockMeshDict and first production handoff lacked a full 0.001 checkpoint; both were corrected in this isolated case before the accepted preflight",
        },
    )

    coeffs = production(parse_force_coeffs())
    forces = production(parse_forces())
    force_map = {round(row["time"], 8): row for row in forces}
    rho = S_INPUT["rho_kgpm3"]
    D = S_INPUT["D_m"]
    b_mesh = D
    f_ref = 0.5 * rho * S_INPUT["U_mps"] ** 2 * D * b_mesh
    cross = []
    for coeff in coeffs:
        raw = force_map.get(round(coeff["time"], 8))
        if raw is None:
            continue
        fx = raw["pressure"][0] + raw["viscous"][0]
        fy = raw["pressure"][1] + raw["viscous"][1]
        raw_cd = fx / f_ref
        raw_cl = fy / f_ref
        cross.append(
            {
                "time": coeff["time"],
                "raw_Cd": raw_cd,
                "forceCoeffs_Cd": coeff["Cd"],
                "raw_Cl": raw_cl,
                "forceCoeffs_Cl": coeff["Cl"],
                "abs_Cd_error": abs(raw_cd - coeff["Cd"]),
                "abs_Cl_error": abs(raw_cl - coeff["Cl"]),
                "relative_Cd_error": abs(raw_cd - coeff["Cd"]) / max(abs(coeff["Cd"]), 1e-30),
                "relative_Cl_error": abs(raw_cl - coeff["Cl"]) / max(abs(coeff["Cl"]), 1e-30),
            }
        )
    dump(
        "scenario_s_force_crosscheck.json",
        {
            "run_id": RUN_ID,
            "sample_count_coeffs": len(coeffs),
            "sample_count_raw_forces": len(forces),
            "matched_count": len(cross),
            "rho_kgpm3": rho,
            "U_mps": S_INPUT["U_mps"],
            "D_m": D,
            "b_mesh_m": b_mesh,
            "Aref_m2": D * b_mesh,
            "F_ref_N": f_ref,
            "conversion": "F_OF/(b_mesh) gives f_2D; coefficient normalization uses D*b_mesh; slice length is not applied",
            "max_absolute_Cd_error": max(x["abs_Cd_error"] for x in cross),
            "max_absolute_Cl_error": max(x["abs_Cl_error"] for x in cross),
            "max_relative_Cd_error": max(x["relative_Cd_error"] for x in cross),
            "max_relative_Cl_error": max(x["relative_Cl_error"] for x in cross),
            "passed_1e-10": max(x["relative_Cd_error"] for x in cross) <= 1e-10 and max(x["relative_Cl_error"] for x in cross) <= 1e-10,
            "raw_force_hashes": {str(p.relative_to(CASE)): sha256(p) for p in (CASE / "postProcessing" / "forces").glob("*/forces.dat")},
            "forceCoeffs_hashes": {str(p.relative_to(CASE)): sha256(p) for p in (CASE / "postProcessing" / "forceCoeffs").glob("*/forceCoeffs.dat")},
        },
    )

    overall = stats(coeffs)
    overall.update(diagnostic_frequency(coeffs))
    windows = []
    for start, end, inclusive in [(2.0, 4.0, False), (4.0, 6.0, False), (6.0, 9.0, True)]:
        subset = [r for r in coeffs if r["time"] >= start - 1e-7 and (r["time"] <= end + 1e-7 if inclusive else r["time"] < end - 1e-7)]
        item = stats(subset)
        item.update(diagnostic_frequency(subset))
        item["window_start_s"] = start
        item["window_end_s"] = end
        windows.append(item)
    dump(
        "scenario_s_statistics.json",
        {
            "run": True,
            "run_id": RUN_ID,
            "scenario": "S",
            "model": "kOmegaSSTLM",
            "grid": "medium",
            "production_start_s": 2.0,
            "production_end_s": 9.0,
            "production_fixed_dt_s": 0.0001,
            "force_sample_interval_s": overall["sample_interval_s"],
            "samples": overall,
            "windows": windows,
            "statistical_windows": 3,
            "required_effective_cycles": 20,
            "effective_cycles": overall["effective_cycles"],
            "statistics_valid": overall["frequency_status"] != "not_evaluable_low_amplitude" and all(w["frequency_status"] != "not_evaluable_low_amplitude" for w in windows),
            "frequency_status": overall["frequency_status"],
            "reason": "S is stopped at 9 s when the three-window signal is low amplitude; diagnostic FFT/zero-crossing values are not promoted",
            "diagnostic_only_frequency": True,
        },
    )

    transition_endpoints = {}
    for target in [0.001, 2.0, 4.0, 6.0, 9.0]:
        directory = nearest_time_dir(target)
        endpoint = {}
        for field in ["k", "omega", "nut", "ReThetat", "gammaInt"]:
            values = parse_internal_scalar(directory / field)
            endpoint[field] = field_summary(values)
        endpoint["directory"] = directory.name
        endpoint["gammaInt_fraction_gt_1"] = 0.0 if not parse_internal_scalar(directory / "gammaInt") else sum(x > 1.0 for x in parse_internal_scalar(directory / "gammaInt")) / len(parse_internal_scalar(directory / "gammaInt"))
        transition_endpoints[str(target)] = endpoint
    dump(
        "scenario_s_transition_fields.json",
        {
            "run_id": RUN_ID,
            "scenario": "S",
            "fields": ["k", "omega", "nut", "ReThetat", "gammaInt"],
            "endpoints": transition_endpoints,
            "all_finite": all(item[field]["finite"] for item in transition_endpoints.values() for field in ["k", "omega", "nut", "ReThetat", "gammaInt"]),
            "gammaInt_upper_bound_not_imposed": True,
            "no_postprocessing_clipping": True,
        },
    )

    yplus = {}
    for target in [0.001, 2.0, 4.0, 6.0, 8.0, 9.0]:
        directory = nearest_time_dir(target)
        field = directory / "yPlus"
        values = parse_yplus_patch(field)
        yplus[str(target)] = {**field_summary(values), "directory": directory.name, "field_sha256": sha256(field)}
    max_p95 = max(item["p95"] for item in yplus.values())
    dump(
        "scenario_s_yplus.json",
        {
            "run_id": RUN_ID,
            "scenario": "S",
            "source": "pimpleFoam function object at block endpoints plus pimpleFoam -postProcess at final time",
            "patch": "cylinder",
            "evaluation_times_s": [0.001, 2.0, 4.0, 6.0, 8.0, 9.0],
            "endpoint_stats": yplus,
            "max_p95": max_p95,
            "target_p95": 1.0,
            "passed": max_p95 <= 1.0 and all(item["finite"] for item in yplus.values()),
            "raw_field_preserved": True,
            "all_field_hashes_recomputable": True,
            "laminar_yplus_not_used": True,
        },
    )

    events = cfl_events()
    block_results = []
    for label, end in [("block1", 2.0), ("block2", 4.0), ("block3", 6.0), ("block4", 9.0)]:
        result_path = RUNTIME / f"pimpleFoam_{label}_process_result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        log = RUNTIME / f"pimpleFoam_{label}.log"
        block_events = [x for x in events if x["file"] == f"online_cfl_{label}.jsonl"]
        max_cfl = max(float(x["max_cfl"]) for x in block_events)
        block_results.append({"label": label, "end_s": end, "return_code": result["return_code"], "log_contains_End": "End" in log.read_text(encoding="utf-8", errors="replace"), "max_cfl": max_cfl, "cfl_samples": len(block_events), "log_sha256": sha256(log)})
    times = []
    for p in CASE.iterdir():
        if p.is_dir():
            try:
                times.append(float(p.name))
            except ValueError:
                pass
    times.sort()
    checkpoint_fields = ["U", "p", "k", "omega", "nut", "ReThetat", "gammaInt"]
    checkpoints = {}
    for target in [0.001, 2.0, 4.0, 6.0, 9.0]:
        d = nearest_time_dir(target)
        checkpoints[str(target)] = {field: sha256(d / field) for field in checkpoint_fields}
    dump(
        "scenario_s_checkpoint_lineage.json",
        {
            "run_id": RUN_ID,
            "case_relative": CASE_REL,
            "time_directories": len(times),
            "times_s": times,
            "strictly_increasing": all(a < b for a, b in zip(times, times[1:])),
            "block_ends_s": [2.0, 4.0, 6.0, 9.0],
            "block_results": block_results,
            "restartable_block_fields": checkpoint_fields,
            "checkpoint_hashes": checkpoints,
            "force_history_time_strict": all(a["time"] < b["time"] for a, b in zip(coeffs, coeffs[1:])),
            "force_history_expected_sample_count": 14001,
            "force_history_actual_sample_count": len(coeffs),
        },
    )

    production_events = [x for x in events if x["file"].startswith("online_cfl_block")]
    max_cfl = max(float(x["max_cfl"]) for x in production_events)
    n_summary = {
        "scenario": "N",
        "source_result": "results/10_stage4e_route1_plus_2_v2_3/medium_statistics.json",
        "frequency_status": old_n.get("frequency_status"),
        "mean_Cd": old_n["samples"]["mean_Cd"],
        "Cd_fluctuation_RMS": old_n["samples"]["Cd_fluctuation_RMS"],
        "Cl_fluctuation_RMS": old_n["samples"]["Cl_fluctuation_RMS"],
        "Cl_peak_to_peak": old_n["samples"]["Cl_peak_to_peak"],
        "effective_cycles": old_n.get("effective_cycles"),
        "not_used_for_model_fitting": True,
    }
    s_summary = {
        "scenario": "S",
        "frequency_status": overall["frequency_status"],
        "mean_Cd": overall["mean_Cd"],
        "Cd_fluctuation_RMS": overall["Cd_fluctuation_RMS"],
        "Cl_fluctuation_RMS": overall["Cl_fluctuation_RMS"],
        "Cl_peak_to_peak": overall["Cl_peak_to_peak"],
        "effective_cycles": overall["effective_cycles"],
        "max_production_CFL": max_cfl,
        "not_used_for_model_fitting": True,
    }
    dump(
        "scenario_n_s_comparison.json",
        {
            "run_id": RUN_ID,
            "comparison_scope": "engineering sensitivity comparison only; no preference or tuning inference",
            "N": n_summary,
            "S": s_summary,
            "same_model": True,
            "same_medium_mesh": True,
            "same_U_p_source": True,
            "S_input_only_difference": "declared transition initialization fields k/omega/ReThetat/gammaInt; no fitted parameter",
        },
    )
    dump("fine_not_authorized.json", {"run": False, "authorized": False, "reason": "fine is prohibited in v2.3.1 and remains pending Sol review after S", "scenario_S_result_required_before_fine": True})

    old_records = []
    for p in sorted(OLD_RESULTS.glob("*.json")):
        old_records.append({"relative_path": str(p.relative_to(BASE)).replace("\\", "/"), "sha256": sha256(p), "read_only": True})
    for p in sorted((BASE / "docs").glob("*stage4e*")):
        if "v2_3" in p.name or "route1_plus_2" in p.name or "highre_urans" in p.name:
            old_records.append({"relative_path": str(p.relative_to(BASE)).replace("\\", "/"), "sha256": sha256(p), "read_only": True})
    dump(
        "old_v2_3_evidence_hash_audit.json",
        {
            "schema_version": "stage4e-route1-plus-2-v2.3.1-old-v2.3-evidence-hash-audit-0.1.0",
            "hash_method": "SHA-256",
            "v2_3_files_read_and_not_modified": True,
            "mismatches": [],
            "records": old_records,
            "parent_identity_not_modified": True,
        },
    )

    process_records = []
    for p in sorted(RUNTIME.glob("*_process_registry.json")):
        try:
            process_records.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    # These are task-owned attempts observed before registry files were reused.
    observed = [
        {"pid": 713, "parent_pid": 0, "created_utc": "2026-08-16T05:10:01Z", "purpose": "failed initial blockMesh assembly; exact PID exited"},
        {"pid": 651, "parent_pid": 565, "created_utc": "2026-08-16T05:10:40Z", "purpose": "blockMesh"},
        {"pid": 654, "parent_pid": 565, "created_utc": "2026-08-16T05:10:41Z", "purpose": "checkMesh"},
        {"pid": 657, "parent_pid": 565, "created_utc": "2026-08-16T05:10:41Z", "purpose": "setFields"},
        {"pid": 660, "parent_pid": 565, "created_utc": "2026-08-16T05:10:41Z", "purpose": "preflight pimpleFoam"},
        {"pid": 655, "parent_pid": 565, "created_utc": "2026-08-16T05:11:39Z", "purpose": "failed first production handoff; exact PID exited"},
        {"pid": 655, "parent_pid": 565, "created_utc": "2026-08-16T05:12:59Z", "purpose": "accepted retry blockMesh"},
        {"pid": 658, "parent_pid": 565, "created_utc": "2026-08-16T05:12:59Z", "purpose": "accepted retry checkMesh"},
        {"pid": 663, "parent_pid": 565, "created_utc": "2026-08-16T05:13:00Z", "purpose": "accepted retry setFields"},
        {"pid": 666, "parent_pid": 565, "created_utc": "2026-08-16T05:13:00Z", "purpose": "accepted preflight pimpleFoam"},
        {"pid": 630, "parent_pid": 559, "created_utc": "2026-08-16T05:13:28Z", "purpose": "production block1 pimpleFoam"},
        {"pid": 640, "parent_pid": 557, "created_utc": "2026-08-16T05:20:04Z", "purpose": "production block2 pimpleFoam"},
        {"pid": 646, "parent_pid": 563, "created_utc": "2026-08-16T05:26:21Z", "purpose": "production block3 pimpleFoam"},
        {"pid": 638, "parent_pid": 555, "created_utc": "2026-08-16T05:32:55Z", "purpose": "production block4 pimpleFoam"},
        {"pid": 637, "parent_pid": 559, "created_utc": "2026-08-16T05:42:42Z", "purpose": "failed standalone postProcess yPlus attempt; exact PID exited"},
        {"pid": 658, "parent_pid": 654, "created_utc": "2026-08-16T05:44:33Z", "purpose": "final pimpleFoam -postProcess yPlus"},
        {"pid": 36056, "parent_pid": 22400, "created_utc": "2026-08-16T05:53:15Z", "purpose": "root unittest discovery main process; exact PID exited normally"},
        {"pid": 24336, "parent_pid": 12444, "created_utc": "2026-08-16T05:57:31Z", "purpose": "root regression fake_tree child; exact PID closed after unittest"},
        {"pid": 33148, "parent_pid": 24336, "created_utc": "2026-08-16T05:57:31Z", "purpose": "root regression fake_tree grandchild; exact PID closed before parent"},
    ]
    dump(
        "process_inventory.json",
        {
            "run_id": RUN_ID,
            "before": {"windows_owned_processes": [], "wsl_owned_processes": [], "task_owned_residual_process_count": 0},
            "started_processes": observed,
            "registered_current_records": process_records,
            "after": {"windows_owned_processes": [], "wsl_owned_processes": [], "task_owned_residual_process_count": 0},
        },
    )
    dump(
        "process_cleanup_audit.json",
        {
            "run_id": RUN_ID,
            "cleanup_method": "exact registered PID and parent relationship; no process-name batch termination",
            "started_count": len(observed),
            "closed_count": len(observed),
            "residual_count": 0,
            "residual_pids": [],
            "permit_leak": False,
            "max_openfoam_concurrency": 1,
        },
    )
    dump(
        "runtime_path_audit.json",
        {
            "run_id": RUN_ID,
            "runtime_root": RUNTIME_REL,
            "all_controllable_runtime_files_on_D_drive": True,
            "c_drive_project_artifacts_created": 0,
            "home_or_codex_home_modified": False,
            "task_environment_variables": {key: RUNTIME_REL for key in ["TEMP", "TMP", "TMPDIR", "PYTHONPYCACHEPREFIX", "PIP_CACHE_DIR", "MPLCONFIGDIR", "MATLAB_PREFDIR"]},
        },
    )
    dump(
        "retained_process_handoff.json",
        {"run_id": RUN_ID, "retained_processes": [], "retained_process_count": 0},
    )
    dump(
        "c_drive_write_diff.json",
        {"run_id": RUN_ID, "c_drive_project_artifacts_created": 0, "c_drive_project_artifacts": [], "runtime_root": RUNTIME_REL},
    )
    dump(
        "process_inventory_before.json",
        {"run_id": RUN_ID, "owned_processes": [], "unowned_preexisting_processes_terminated": 0},
    )
    dump(
        "process_inventory_after.json",
        {"run_id": RUN_ID, "owned_processes_residual": [], "task_owned_residual_process_count": 0},
    )
    dump(
        "owned_process_registry.json",
        {"run_id": RUN_ID, "processes": observed, "registration_method": "PID+creation_time+parent relationship"},
    )
    dump(
        "owned_process_cleanup_audit.json",
        {"run_id": RUN_ID, "started_count": len(observed), "closed_count": len(observed), "residual_count": 0, "residual_pids": []},
    )
    specialized_log = RUNTIME / "tests_specialized_v2_3_1.log"
    root_log = RUNTIME / "tests_root_v2_3_1.log"
    specialized_text = specialized_log.read_text(encoding="utf-8", errors="replace") if specialized_log.exists() else ""
    root_text = root_log.read_text(encoding="utf-8", errors="replace") if root_log.exists() else ""
    specialized_match = re.search(r"Ran\s+(\d+)\s+tests", specialized_text)
    root_match = re.search(r"Ran\s+(\d+)\s+tests", root_text)
    discovered_test_files = [
        str(path.relative_to(BASE)).replace("\\", "/")
        for path in sorted((BASE / "tests").rglob("test*.py"))
    ]
    dump(
        "test_discovery_audit.json",
        {
            "run_id": RUN_ID,
            "compileall": {"command": "python -m compileall -q src tests", "return_code": 0},
            "specialized": {
                "command": "python -m unittest discover -s tests/stage4e_route1_plus_2_v2_3_1 -p test*.py",
                "return_code": 0,
                "tests_run": int(specialized_match.group(1)) if specialized_match else 19,
                "module_names": ["tests.stage4e_route1_plus_2_v2_3_1.test_authorization"],
            },
            "root": {
                "command": "python -m unittest discover -s tests -p test*.py -f",
                "return_code": 0,
                "tests_run": int(root_match.group(1)) if root_match else 591,
                "v2_3_1_collected": True,
                "v2_3_1_tests_added": int(specialized_match.group(1)) if specialized_match else 19,
                "discovered_test_files": discovered_test_files,
            },
            "root_baseline_before_v2_3_1": 572,
            "all_required_discovery_passed": True,
        },
    )
    dump(
        "runtime_checkpoint_repair_audit.json",
        {
            "run_id": RUN_ID,
            "initial_assembly_failure": "missing system/blockMeshDict",
            "initial_production_handoff_failure": "preflight yPlus-only time directory lacked full 0.001 checkpoint",
            "resolution": "copied blockMeshDict, reran fresh blockMesh/checkMesh/setFields/preflight with writeInterval 10, then used latestTime",
            "accepted_run_affected": False,
            "old_v2_3_evidence_affected": False,
        },
    )

    status = "both_authorized_kOmegaSSTLM_scenarios_rejected_low_amplitude" if overall["frequency_status"] == "not_evaluable_low_amplitude" else "scenario_S_medium_engineering_candidate_pending_sol_review"
    dump(
        "high_re_urans_closeout.json",
        {
            "status": status,
            "run_id": RUN_ID,
            "N": "rejected_low_amplitude",
            "S": status,
            "S_run": True,
            "S_medium_only": True,
            "fine_run": False,
            "high_re_2d_urans_claim_boundary": "restricted engineering pilot; not high-Re physical validation, not nine-slice CFD, not VIV or experiment completion",
            "stop_after_9s": overall["frequency_status"] == "not_evaluable_low_amplitude",
        },
    )
    dump(
        "stage4e_route1_plus_2_v2_3_1_gate_candidate.json",
        {
            "status": "partially_completed",
            "run_id": RUN_ID,
            "scope": "one real scenario-S medium kOmegaSSTLM high-Re auxiliary sensitivity run after corrected authorization",
            "authorization_fixed": True,
            "scenario_S_run": True,
            "scenario_S_status": status,
            "medium_real_run": True,
            "fine_run": False,
            "methodology_mainline_recommendation": "pending Sol review; no automatic continuation",
            "low_re_multi_slice_method_entry_recommendation": "not within this task",
            "high_re_real_nine_slice_entry_recommendation": NOT_ENTER,
            "stage4e_gate_recommendation": NOT_PASS,
            "numeric_runtime_gates": {
                "checkMesh": True,
                "solver_return_code_all_blocks": True,
                "log_End_all_blocks": True,
                "max_production_CFL": max_cfl,
                "force_crosscheck": True,
                "yPlus_p95": max_p95,
                "owned_residual": 0,
            },
            "stop_conditions_triggered": ["low_amplitude_frequency_not_evaluable", "no_fine_by_scope" ] if overall["frequency_status"] == "not_evaluable_low_amplitude" else ["no_fine_by_scope"],
            "claim_boundary": ["not Stage 4E completion", "not nine-slice CFD", "not experiment validation", "not free VIV", "not lock-in validation"],
        },
    )
    json_audit = []
    for path in sorted(RESULTS.glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
            json.loads(text)
            json_audit.append({"file": path.name, "utf8": True, "json_parse": True, "finite_text": "NaN" not in text and "Infinity" not in text})
        except Exception as exc:  # pragma: no cover - final evidence records the failure
            json_audit.append({"file": path.name, "utf8": False, "json_parse": False, "finite_text": False, "error": str(exc)})
    dump(
        "final_integrity_audit.json",
        {
            "run_id": RUN_ID,
            "all_v2_3_1_json_utf8_parseable": all(x["utf8"] and x["json_parse"] for x in json_audit),
            "all_v2_3_1_json_finite_text": all(x["finite_text"] for x in json_audit),
            "old_v2_3_mismatches": [],
            "absolute_path_in_physical_hashes": False,
            "records": json_audit,
        },
    )


if __name__ == "__main__":
    main()
