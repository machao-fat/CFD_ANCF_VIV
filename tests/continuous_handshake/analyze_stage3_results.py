"""Create compact quantitative summaries for the stage-three acceptance audit."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def f(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def rms(values: list[float]) -> float:
    return math.sqrt(mean([value * value for value in values]))


def dominant_frequency(t: list[float], x: list[float]) -> float:
    """Estimate frequency from positive-going zero crossings without NumPy."""
    if len(x) < 8:
        return 0.0
    baseline = mean(x)
    y = [value - baseline for value in x]
    if max((abs(value) for value in y), default=0.0) <= 1.0e-14:
        return 0.0
    crossings: list[float] = []
    for i in range(1, len(y)):
        if y[i - 1] <= 0.0 < y[i]:
            fraction = -y[i - 1] / (y[i] - y[i - 1]) if y[i] != y[i - 1] else 0.0
            crossings.append(t[i - 1] + fraction * (t[i] - t[i - 1]))
    periods = [b - a for a, b in zip(crossings, crossings[1:]) if b > a]
    return 1.0 / mean(periods) if periods else 0.0


def audit_metrics(path: Path, *, skip_startup: bool = False) -> dict[str, Any]:
    rows = csv_rows(path)
    if not rows:
        return {"status": "empty", "path": str(path)}
    t = [f(r, "time_s") for r in rows]
    y = [f(r, "corrected_y_m", f(r, "y_m")) for r in rows]
    v = [f(r, "corrected_vy_mps", f(r, "vy_mps")) for r in rows]
    fy = [f(r, "force_y_N") for r in rows]
    power = [f(r, "instantaneous_power_W") for r in rows]
    n0 = len(rows) // 2
    if skip_startup:
        for i, row in enumerate(rows):
            if f(row, "startup_fixed") < 0.5:
                n0 = max(n0, i)
                break
    wt = slice(n0, None)
    tw, yw, fw = t[wt], y[wt], fy[wt]
    dt = mean([b - a for a, b in zip(t, t[1:])]) if len(t) > 1 else 0.0
    fluid_work = sum(0.5 * (power[i] + power[i - 1]) * (t[i] - t[i - 1]) for i in range(max(1, n0 + 1), len(t)))
    residual_d = [abs(f(r, "predicted_displacement_residual_m", f(r, "predictor_displacement_residual_m"))) for r in rows]
    residual_v = [abs(f(r, "predicted_velocity_residual_mps", f(r, "predictor_velocity_residual_mps"))) for r in rows]
    energy = [f(r, "mechanical_energy_J") for r in rows]
    return {
        "status": "complete", "path": str(path), "steps": len(rows), "last_time_s": t[-1], "dt_s": dt,
        "rms_y_m_last_half": rms(yw), "peak_y_m_last_half": max((abs(value) for value in yw), default=0.0),
        "rms_force_y_N_last_half": rms(fw),
        "dominant_displacement_frequency_Hz": dominant_frequency(tw, yw),
        "dominant_force_frequency_Hz": dominant_frequency(tw, fw),
        "mean_power_W_last_half": mean(power[wt]), "fluid_work_J_last_half": fluid_work,
        "max_predictor_displacement_residual_m": max(residual_d, default=0.0),
        "max_predictor_velocity_residual_mps": max(residual_v, default=0.0),
        "max_structure_residual": max((abs(f(r, "structure_residual")) for r in rows), default=0.0),
        "max_structure_iterations": int(max((f(r, "structure_iterations") for r in rows), default=0.0)),
        "min_tension_N": min((f(r, "min_tension_N") for r in rows), default=0.0),
        "mechanical_energy_increment_J": energy[-1] - energy[n0] if energy else 0.0,
        "energy_balance_residual_J_last_half": fluid_work - (energy[-1] - energy[n0] if energy else 0.0),
    }


def structure_comparison(eb: Path, ancf: Path) -> dict[str, Any]:
    e, a = csv_rows(eb), csv_rows(ancf)
    n = min(len(e), len(a))
    ey = [f(r, "corrected_y_m") for r in e[:n]]
    ay = [f(r, "corrected_y_m") for r in a[:n]]
    ef = [f(r, "force_y_N") for r in e[:n]]
    af = [f(r, "force_y_N") for r in a[:n]]
    t = [f(r, "time_s") for r in e[:n]]
    h = n // 2
    def rel_rms(x: list[float], y: list[float]) -> float:
        return rms([a - b for a, b in zip(x, y)]) / max(1.0e-12, rms(y))
    return {
        "common_steps": n, "time_end_s": t[-1] if n else 0.0,
        "displacement_rms_difference_m": rms([a - b for a, b in zip(ey, ay)]),
        "displacement_relative_rms_difference": rel_rms(ey[h:], ay[h:]) if n else 0.0,
        "displacement_max_difference_m": max((abs(a - b) for a, b in zip(ey, ay)), default=0.0),
        "force_relative_rms_difference": rel_rms(ef[h:], af[h:]) if n else 0.0,
        "eb_frequency_Hz": dominant_frequency(t[h:], ey[h:]),
        "ancf_frequency_Hz": dominant_frequency(t[h:], ay[h:]),
        "eb_mean_power_W_last_half": mean([f(r, "instantaneous_power_W") for r in e[h:]]),
        "ancf_mean_power_W_last_half": mean([f(r, "instantaneous_power_W") for r in a[h:]]),
    }


def time_step_comparison(reference: Path, refined: Path) -> dict[str, Any]:
    coarse = [r for r in csv_rows(reference) if f(r, "time_s") <= 0.25 + 1.0e-12]
    fine = csv_rows(refined)
    cy = [f(r, "corrected_y_m") for r in coarse]
    fy = [f(r, "corrected_y_m") for r in fine]
    # Compare at coincident times; the refined run has two samples per coarse
    # step, so direct interpolation is unnecessary for the endpoint metrics.
    return {
        "coarse_steps": len(coarse), "refined_steps": len(fine),
        "coarse_dt_s": mean([f(coarse[i + 1], "time_s") - f(coarse[i], "time_s") for i in range(len(coarse) - 1)]),
        "refined_dt_s": mean([f(fine[i + 1], "time_s") - f(fine[i], "time_s") for i in range(len(fine) - 1)]),
        "coarse_peak_y_m": max((abs(v) for v in cy), default=0.0),
        "refined_peak_y_m": max((abs(v) for v in fy), default=0.0),
        "coarse_mean_power_W": mean([f(r, "instantaneous_power_W") for r in coarse]),
        "refined_mean_power_W": mean([f(r, "instantaneous_power_W") for r in fine]),
    }


def sdof_campaign(results_root: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted(results_root.glob("04_single_dof_free_viv_Ur*/sdof_audit.csv")):
        record = audit_metrics(path, skip_startup=True)
        params = json.loads((path.parent / "parameters.json").read_text(encoding="utf-8"))
        if record.get("last_time_s", 0.0) < 9.999:
            record["status"] = "partial"
        record.update({"Ur": params["reduced_velocity"], "mass_ratio": params["mass_ratio"], "damping_ratio": params["damping_ratio"], "fn_Hz": params["natural_frequency_hz"]})
        record["frequency_ratio_f_over_fn"] = record["dominant_displacement_frequency_Hz"] / params["natural_frequency_hz"] if params["natural_frequency_hz"] else None
        out.append(record)
    return out


def parse_forces_dat(path: Path, dt: float) -> dict[int, float]:
    vector = re.compile(r"\(\(([^()]*)\)\s*\(([^()]*)\)\)")
    out: dict[int, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        match = re.match(r"\s*([-+0-9.eE]+)\s+", line)
        groups = vector.search(line)
        if not match or not groups:
            continue
        try:
            time_s = float(match.group(1))
            pressure = [float(v) for v in groups.group(1).split()]
            viscous = [float(v) for v in groups.group(2).split()]
            if len(pressure) == 3 and len(viscous) == 3:
                out[int(round(time_s / dt))] = pressure[1] + viscous[1]
        except ValueError:
            continue
    return out


def online_replay_summary() -> dict[str, Any]:
    base = ROOT / "results" / "03_prescribed_motion_extended" / "discretization_run2" / "near_shedding_medium_backward" / "force" / "forces.csv"
    online0 = ROOT / "cases" / "openfoam" / "online_motion_long_replay_run8" / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
    online_restart = ROOT / "cases" / "openfoam" / "online_motion_long_replay_run8" / "postProcessing" / "cylinderForces" / "40.5" / "forces.dat"
    reference = {int(round(f(r, "time_s") / 0.0025)): f(r, "total_force_y_N") for r in csv_rows(base) if f(r, "time_s") <= 62.5}
    actual = parse_forces_dat(online0, 0.0025)
    actual.update(parse_forces_dat(online_restart, 0.0025))
    errors = [actual[k] - reference[k] for k in actual if k in reference]
    base_values = [reference[k] for k in actual if k in reference]
    denom = rms(base_values)
    publisher = ROOT / "cases" / "openfoam" / "online_motion_long_replay_run8" / "coupling" / "motion_publisher_status.json"
    load_status = ROOT / "cases" / "openfoam" / "online_motion_long_replay_run8" / "coupling" / "load_publisher_status.json"
    return {
        "target_cycles": 10, "target_end_time_s": 62.5, "target_steps": 25000,
        "motion_publisher": json.loads(publisher.read_text(encoding="utf-8")) if publisher.exists() else None,
        "load_publisher": json.loads(load_status.read_text(encoding="utf-8")) if load_status.exists() else None,
        "force_samples_compared": len(errors),
        "force_y_rmse_N": math.sqrt(mean([e * e for e in errors])) if errors else None,
        "force_y_relative_rmse": math.sqrt(mean([e * e for e in errors])) / denom if errors and denom else None,
        "force_y_mean_abs_difference_N": mean([abs(e) for e in errors]) if errors else None,
        "trajectory_definition": "y=0.1*sin(1.00530964914873*t), exact same analytical trajectory",
        "restart": {"from_step": 16200, "from_time_s": 40.5, "to_step": 25000, "to_time_s": 62.5, "fresh_consumed_directory": True},
    }


def main() -> None:
    continuous = ROOT / "results" / "04_continuous_fsi"
    comparison_dir = ROOT / "results" / "04_ancf_eb_online_comparison"
    continuous.mkdir(parents=True, exist_ok=True)
    comparison_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "04_online_motion_long_replay").mkdir(parents=True, exist_ok=True)
    eb_path = ROOT / "results" / "04_single_slice_eb_fsi_run7" / "coupling_audit.csv"
    ancf_path = ROOT / "results" / "04_single_slice_ancf_fsi_continuous_run2" / "coupling_audit.csv"
    eb_dt2_path = ROOT / "results" / "04_single_slice_eb_fsi_dt2_run2" / "coupling_audit.csv"
    payload = {"eb_1000": audit_metrics(eb_path), "ancf_1000": audit_metrics(ancf_path), "eb_dt2_200": audit_metrics(eb_dt2_path), "time_step_comparison": time_step_comparison(eb_path, eb_dt2_path), "eb_ancf_comparison": structure_comparison(eb_path, ancf_path), "sdof_campaign": sdof_campaign(ROOT / "results"), "online_replay": online_replay_summary()}
    (continuous / "stage3_quantitative_summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (comparison_dir / "ancf_eb_online_comparison.json").write_text(json.dumps(payload["eb_ancf_comparison"], indent=2) + "\n", encoding="utf-8")
    (ROOT / "results" / "04_online_motion_long_replay" / "online_vs_analytic.json").write_text(json.dumps(payload["online_replay"], indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
