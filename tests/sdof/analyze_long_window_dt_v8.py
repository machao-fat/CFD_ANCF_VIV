"""Analyze same-late-checkpoint Ur=5.2 dt/dt2 convergence by response cycles."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .analyze_long_sdof import merge_rows
    from .analyze_response_cycle_aligned_v6 import dft_frequency, positive_crossings
except ImportError:  # pragma: no cover
    from analyze_long_sdof import merge_rows
    from analyze_response_cycle_aligned_v6 import dft_frequency, positive_crossings


def _boundary_rows(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    times = np.asarray([row["time_s"] for row in rows], dtype=float)
    if start < times[0] - 1.0e-9 or end > times[-1] + 1.0e-9:
        raise ValueError("cycle boundary outside audit range")
    selected = [row for row in rows if start < row["time_s"] < end]
    fields = list(rows[0])
    out = []
    for boundary in (start, end):
        if abs(boundary - times[0]) <= 1.0e-12:
            source = rows[0]
        elif abs(boundary - times[-1]) <= 1.0e-12:
            source = rows[-1]
        else:
            idx = int(np.searchsorted(times, boundary))
            left, right = rows[idx - 1], rows[idx]
            alpha = (boundary - left["time_s"]) / (right["time_s"] - left["time_s"])
            source = {key: left[key] + alpha * (right[key] - left[key]) for key in fields if key not in ("step", "startup_fixed")}
            source["step"] = left["step"]
            source["startup_fixed"] = left.get("startup_fixed", 0)
            source["time_s"] = boundary
        out.append(dict(source))
    out = [out[0], *selected, out[1]]
    out.sort(key=lambda row: row["time_s"])
    return out


def _trap(rows: list[dict[str, float]], key: str) -> float:
    return float(np.trapz([row[key] for row in rows], [row["time_s"] for row in rows]))


def _metric(rows: list[dict[str, float]], start: float, end: float, log_path: Path, dt: float, actual_cycles: int) -> dict[str, Any]:
    block = _boundary_rows(rows, start, end)
    t = np.asarray([row["time_s"] for row in block], dtype=float)
    y = np.asarray([row["y_m"] for row in block], dtype=float)
    fy = np.asarray([row["force_y_N"] for row in block], dtype=float)
    cl = np.asarray([row["Cl"] for row in block], dtype=float)
    response_frequency = float(dft_frequency(y.tolist(), t.tolist()))
    lift_frequency = float(dft_frequency(fy.tolist(), t.tolist()))
    fluid_work = _trap(block, "instantaneous_power_W")
    damping = float(block[-1]["damping_dissipation_J"] - block[0]["damping_dissipation_J"])
    mechanical = float(block[-1]["mechanical_energy_J"] - block[0]["mechanical_energy_J"])
    energy_residual = fluid_work - damping - mechanical
    energy_relative = abs(energy_residual) / max(abs(fluid_work), abs(damping), abs(mechanical), 1.0e-30)
    cfl = _max_cfl(log_path)
    return {
        "start_s": start,
        "end_s": end,
        "actual_response_cycles": actual_cycles,
        "samples": len(block),
        "dt_s": dt,
        "y_rms_m": float(np.sqrt(np.mean(y * y))),
        "y_min_m": float(np.min(y)),
        "y_max_m": float(np.max(y)),
        "half_amplitude_m": float(0.5 * (np.max(y) - np.min(y))),
        "fy_rms_N": float(np.sqrt(np.mean(fy * fy))),
        "Cl_rms": float(np.sqrt(np.mean(cl * cl))),
        "Cd_mean": float(np.mean([row["Cd"] for row in block])),
        "response_frequency_Hz_dft": response_frequency,
        "lift_frequency_Hz_dft": lift_frequency,
        "mean_power_W": float(fluid_work / (end - start)),
        "fluid_work_J": fluid_work,
        "damping_dissipation_J": damping,
        "mechanical_energy_change_J": mechanical,
        "energy_residual_J": energy_residual,
        "energy_residual_relative": energy_relative,
        "max_abs_y_m": float(np.max(np.abs(y))),
        "max_cfl": cfl,
        "finite": bool(np.all(np.isfinite(y)) and np.all(np.isfinite(fy)) and np.all(np.isfinite(cl))),
        "mesh_safety_pass": _mesh_safety(log_path),
    }


def _max_cfl(path: Path) -> float:
    pattern = re.compile(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)")
    values = [float(m.group(1)) for m in pattern.finditer(path.read_text(encoding="utf-8", errors="replace"))] if path.exists() else []
    return max(values, default=float("nan"))


def _mesh_safety(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    # OpenFOAM's normal ``FOAM_SIGFPE`` startup line contains the words
    # "floating point exception"; it is not a runtime failure.  Only match
    # actual fatal/mesh failure signatures here.
    bad = ("negative volume", "mesh failed", "fatal error", "stack trace")
    finite_error = any(re.search(r"\b(?:nan|inf)\b", line) and "sigfpe" not in line for line in text.splitlines())
    return not any(token in text for token in bad) and not finite_error


def _last_five_cycle_window(rows: list[dict[str, float]]) -> tuple[float, float, list[float]]:
    times = [row["time_s"] for row in rows]
    values = [row["y_m"] for row in rows]
    crossings = positive_crossings(values, times)
    if len(crossings) < 4:
        raise ValueError(f"fewer than three complete positive-going response cycles: {len(crossings)} crossings")
    cycle_count = 5 if len(crossings) >= 6 else 3
    selected = crossings[-(cycle_count + 1):]
    return float(selected[0]), float(selected[-1]), [float(value) for value in selected]


def _relative(a: float, b: float) -> float:
    return abs(b - a) / max(abs(a), 1.0e-30)


def analyze_branch(rows: list[dict[str, float]], log: Path, dt: float) -> dict[str, Any]:
    start, end, crossings = _last_five_cycle_window(rows)
    periods = [b - a for a, b in zip(crossings, crossings[1:])]
    return {"window": _metric(rows, start, end, log, dt, len(periods)), "positive_crossings_s": crossings, "periods_s": periods, "response_frequency_Hz_zero_crossing": float(1.0 / np.mean(periods))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse-audit", type=Path, required=True)
    parser.add_argument("--fine-audit", type=Path, required=True)
    parser.add_argument("--coarse-log", type=Path, required=True)
    parser.add_argument("--fine-log", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--coarse-checkpoint", type=Path, required=True)
    parser.add_argument("--fine-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    coarse_initial = json.loads(args.coarse_checkpoint.read_text(encoding="utf-8-sig"))
    fine_initial = json.loads(args.fine_checkpoint.read_text(encoding="utf-8-sig"))
    # The branch checkpoint files are final states after continuation.  The
    # immutable common manifest is the authoritative initial-state evidence.
    common_state = manifest["state"]
    same_late_state = (
        manifest["common_physical_time_s"] == 130.0
        and manifest["common_source_step"] == 52000
        and manifest["same_cfd_initial_field_required"]
        and manifest["parameters_modified"] is False
        and (Path(manifest["branches"][0]["case"]) / "130").exists()
        and (Path(manifest["branches"][1]["case"]) / "130").exists()
        and math.isfinite(float(common_state["y"]))
        and math.isfinite(float(common_state["v"]))
        and math.isfinite(float(common_state["a"]))
    )
    coarse_rows_all = merge_rows([args.coarse_audit])
    fine_rows_all = merge_rows([args.fine_audit])
    coarse_end_committed = float(coarse_initial["state"]["time_s"])
    fine_end_committed = float(fine_initial["state"]["time_s"])
    coarse_rows = [row for row in coarse_rows_all if row["time_s"] <= coarse_end_committed + 1.0e-9]
    fine_rows = [row for row in fine_rows_all if row["time_s"] <= fine_end_committed + 1.0e-9]
    coarse = analyze_branch(coarse_rows, args.coarse_log, 0.0025)
    fine = analyze_branch(fine_rows, args.fine_log, 0.00125)
    cwin, fwin = coarse["window"], fine["window"]
    common_window = [max(cwin["start_s"], fwin["start_s"]), min(cwin["end_s"], fwin["end_s"])]
    comparison = {}
    for key in ("y_rms_m", "half_amplitude_m", "fy_rms_N", "Cl_rms", "Cd_mean", "response_frequency_Hz_dft", "lift_frequency_Hz_dft", "mean_power_W", "fluid_work_J", "damping_dissipation_J", "mechanical_energy_change_J", "energy_residual_relative"):
        comparison[key + "_relative_change"] = _relative(float(cwin[key]), float(fwin[key]))
    criteria = {
        "same_late_checkpoint_state": same_late_state,
        "at_least_three_actual_response_cycles": cwin["actual_response_cycles"] >= 3 and fwin["actual_response_cycles"] >= 3,
        "y_rms_lt_5pct": comparison["y_rms_m_relative_change"] < 0.05,
        "half_amplitude_lt_5pct": comparison["half_amplitude_m_relative_change"] < 0.05,
        "fy_rms_lt_5pct": comparison["fy_rms_N_relative_change"] < 0.05,
        "Cl_rms_lt_5pct": comparison["Cl_rms_relative_change"] < 0.05,
        "Cd_mean_reported": math.isfinite(float(cwin["Cd_mean"])) and math.isfinite(float(fwin["Cd_mean"])),
        "response_frequency_lt_2pct": comparison["response_frequency_Hz_dft_relative_change"] < 0.02,
        "lift_frequency_reported": math.isfinite(float(cwin["lift_frequency_Hz_dft"])) and math.isfinite(float(fwin["lift_frequency_Hz_dft"])),
        "mean_power_lt_10pct": comparison["mean_power_W_relative_change"] < 0.10,
        "energy_residual_coarse_lt_10pct": cwin["energy_residual_relative"] < 0.10,
        "energy_residual_fine_lt_10pct": fwin["energy_residual_relative"] < 0.10,
        "finite": cwin["finite"] and fwin["finite"],
        "mesh_safety": cwin["mesh_safety_pass"] and fwin["mesh_safety_pass"],
        "cfl_lt_0p5": (not math.isfinite(float(cwin["max_cfl"])) or cwin["max_cfl"] < 0.5) and (not math.isfinite(float(fwin["max_cfl"])) or fwin["max_cfl"] < 0.5),
        "displacement_lt_1p5D": cwin["max_abs_y_m"] < 1.5 and fwin["max_abs_y_m"] < 1.5,
    }
    output = {
        "schema_version": "long_window_dt_convergence_v8",
        "status": "formal_long_window_convergence_pass" if all(criteria.values()) else "formal_long_window_convergence_failed",
        "same_late_checkpoint_state": same_late_state,
        "common_checkpoint_time_s": 130.0,
        "common_checkpoint_manifest": str(args.manifest),
        "coarse_dt_s": 0.0025,
        "refined_dt_s": 0.00125,
        "coarse": coarse,
        "refined": fine,
        "actual_response_cycles": {"coarse": cwin["actual_response_cycles"], "refined": fwin["actual_response_cycles"]},
        "common_physical_window_s": common_window,
        "comparison_relative_changes": comparison,
        "criteria": criteria,
        "long_window_convergence_pass": all(criteria.values()),
        "window_definition": "the last five complete positive-going displacement zero-crossing cycles when available, otherwise the minimum three-cycle formal window; statistics compared, no pointwise time-series error used",
        "initial_state": {"common_state": common_state, "coarse_final_checkpoint": str(args.coarse_checkpoint), "fine_final_checkpoint": str(args.fine_checkpoint)},
        "audit_rows": {"coarse_total_read": len(coarse_rows_all), "coarse_used_through_committed_checkpoint": len(coarse_rows), "fine_total_read": len(fine_rows_all), "fine_used_through_committed_checkpoint": len(fine_rows)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "same_late_checkpoint_state": same_late_state, "cycles": output["actual_response_cycles"], "comparison": comparison, "criteria": criteria}, indent=2))


if __name__ == "__main__":
    main()
