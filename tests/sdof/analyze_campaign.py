from __future__ import annotations

import csv
import json
import math
import re
import statistics
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]


def detrend(values: list[float]) -> list[float]:
    n = len(values)
    if n < 2:
        return values[:]
    xbar = (n-1)/2
    ybar = statistics.fmean(values)
    slope = sum((i-xbar)*(v-ybar) for i, v in enumerate(values))/max(sum((i-xbar)**2 for i in range(n)), 1e-30)
    return [v-(ybar+slope*(i-xbar)) for i, v in enumerate(values)]


def dominant_frequency(values: list[float], dt: float, fmin: float = 0.01) -> float:
    x = detrend(values)
    n = len(x)
    if n < 8:
        return 0.0
    best_f, best_a = 0.0, -1.0
    fmax = 0.5/dt
    # A frequency grid finer than the raw DFT bins makes the output usable
    # for the short screening windows; the accepted campaign still reports
    # the window length and frequency resolution explicitly.
    df = 1.0/(n*dt*4.0)
    f = fmin
    while f <= fmax:
        re = sum(v*math.cos(2*math.pi*f*i*dt) for i, v in enumerate(x))
        im = sum(v*math.sin(2*math.pi*f*i*dt) for i, v in enumerate(x))
        amp = re*re+im*im
        if amp > best_a:
            best_a, best_f = amp, f
        f += df
    return best_f


def zero_crossing_frequency(values: list[float], times: list[float]) -> float:
    # Remove constant and linear trends before locating crossings.  This
    # keeps the estimator usable for biased or slowly drifting signals.
    values = detrend(values)
    crossings = []
    for i in range(1, len(values)):
        if values[i-1] <= 0 < values[i] or values[i-1] >= 0 > values[i]:
            dv = values[i]-values[i-1]
            frac = -values[i-1]/dv if dv else 0.0
            crossings.append(times[i-1]+frac*(times[i]-times[i-1]))
    if len(crossings) < 3:
        return 0.0
    periods = [crossings[i+2]-crossings[i] for i in range(len(crossings)-2)]
    # crossings[i+2]-crossings[i] spans two alternating-sign crossings,
    # i.e. one complete period.  The previous factor 2.0 was a doubled
    # frequency error.
    return 1.0/statistics.fmean(periods)


def relative_frequency_difference(primary: float, diagnostic: float) -> float:
    """Return a bounded, explicitly labelled DFT/zero-crossing difference."""
    if primary <= 0.0 or diagnostic <= 0.0:
        return float("inf")
    return abs(primary - diagnostic) / abs(primary)


def frequency_reliable(primary: float, diagnostic: float, *, tolerance: float = 0.05) -> bool:
    """Reliability gate for a frequency pair, not a lock-in classifier."""
    return relative_frequency_difference(primary, diagnostic) < tolerance


def analyze(path: Path, Ur: float, *, rho: float = 1000.0, U: float = 1.0, D: float = 1.0) -> dict[str, object]:
    rows = read_rows(path)
    if not rows:
        return {"status": "empty", "path": str(path)}
    stable = [r for r in rows if r["time_s"] >= rows[-1]["time_s"]*0.5 and r["startup_fixed"] < 0.5]
    if not stable:
        stable = rows[len(rows)//2:]
    t = [r["time_s"] for r in stable]
    y = [r["y_m"] for r in stable]
    fy = [r["force_y_N"] for r in stable]
    dt = statistics.fmean([r["time_s"]-rows[i-1]["time_s"] for i, r in enumerate(rows) if i])
    fn = U/(Ur*D)
    window_time = t[-1]-t[0] if len(t)>1 else 0.0
    stable_cycles = window_time*fn
    y0 = detrend(y)
    f_y = dominant_frequency(y, dt)
    f_l = dominant_frequency(fy, dt)
    z_y = zero_crossing_frequency(y0, t)
    z_l = zero_crossing_frequency(fy, t)
    response_frequency_difference = relative_frequency_difference(f_y, z_y)
    lift_frequency_difference = relative_frequency_difference(f_l, z_l)
    cfd_work_window = sum(r["force_y_N"]*r.get("predicted_vy_mps", 0.0)*dt for r in stable)
    structure_work_window = sum(r["force_y_N"]*r["vy_mps"]*dt for r in stable)
    coupling_defect_window = cfd_work_window-structure_work_window
    damping_window = stable[-1].get("damping_dissipation_J", 0.0)-stable[0].get("damping_dissipation_J", 0.0)
    mechanical_delta = stable[-1].get("mechanical_energy_J", 0.0)-stable[0].get("mechanical_energy_J", 0.0)
    energy_balance = structure_work_window-mechanical_delta-damping_window
    return {
        "status": "accepted_window" if stable_cycles >= 10 else "screening_only",
        "path": str(path), "steps": len(rows), "last_time_s": rows[-1]["time_s"], "dt_s": dt,
        "Ur": Ur, "mass_ratio": 10.0, "damping_ratio": 0.01, "fn_Hz": fn,
        "stable_window_start_s": t[0], "stable_window_end_s": t[-1], "stable_window_cycles": stable_cycles,
        "frequency_resolution_Hz": 1.0/max(window_time, 1e-30),
        "A_over_D_rms": math.sqrt(statistics.fmean(v*v for v in y))/D,
        "A_over_D_peak": max(abs(v) for v in y)/D,
        "Cl_rms": math.sqrt(statistics.fmean(v*v for v in [r["Cl"] for r in stable])),
        "Cd_mean": statistics.fmean(r["Cd"] for r in stable),
        "response_frequency_Hz_dft": f_y, "lift_frequency_Hz_dft": f_l,
        # Compatibility aliases retained for old consumers.  These fields
        # are direct-DFT values, not zero-crossing values.
        "response_frequency_Hz_fft": f_y, "lift_frequency_Hz_fft": f_l,
        "response_frequency_Hz_zero_crossing": z_y,
        "lift_frequency_Hz_zero_crossing": z_l,
        "response_frequency_Hz": f_y,
        "lift_frequency_Hz": f_l,
        "response_frequency_method": "dft_primary",
        "lift_frequency_method": "dft_primary",
        "response_frequency_reliable": frequency_reliable(f_y, z_y),
        "lift_zero_crossing_reliable": frequency_reliable(f_l, z_l),
        "response_dft_zero_crossing_relative_difference": response_frequency_difference,
        "lift_dft_zero_crossing_relative_difference": lift_frequency_difference,
        "f_over_fn_dft": f_y/fn if fn else 0.0,
        "lift_f_over_fn_dft": f_l/fn if fn else 0.0,
        "f_over_fn_fft": f_y/fn if fn else 0.0,
        "lift_f_over_fn_fft": f_l/fn if fn else 0.0,
        "f_over_fn_zero_crossing": z_y/fn if fn else 0.0,
        "lift_f_over_fn_zero_crossing": z_l/fn if fn else 0.0,
        "frequency_methods": {
            "dft": "dominant_frequency direct DFT on detrended samples",
            "zero_crossing": "linear-interpolated alternating-sign crossings; one full period per two crossings",
            "lift_primary": "detrended DFT spectral peak; zero crossing is diagnostic only",
            "fft_legacy_fields": "compatibility aliases for the direct DFT values; not zero-crossing values",
        },
        "mean_power_W": statistics.fmean(r["instantaneous_power_W"] for r in stable),
        "W_CFD_predicted_J_window": cfd_work_window,
        "W_structure_corrected_J_window": structure_work_window,
        "E_coupling_defect_J_window": coupling_defect_window,
        "mechanical_energy_change_J_window": mechanical_delta,
        "structure_energy_balance_residual_J_window": energy_balance,
        "structure_energy_balance_relative_window": abs(energy_balance)/max(abs(structure_work_window), abs(mechanical_delta), 1e-30),
        "fluid_work_J_window": stable[-1]["fluid_work_J"]-stable[0]["fluid_work_J"],
        "damping_dissipation_J_window": stable[-1]["damping_dissipation_J"]-stable[0]["damping_dissipation_J"],
        "max_abs_predictor_displacement_residual_m": max(abs(r["predictor_displacement_residual_m"]) for r in stable),
        "max_abs_predictor_velocity_residual_mps": max(abs(r["predictor_velocity_residual_mps"]) for r in stable),
        "max_abs_y_m": max(abs(r["y_m"]) for r in rows),
        "cfl_and_mesh_quality": "see pimpleFoam log; no automatic mesh-quality function object is present in this campaign",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    base = root / "results/04_sdof_viv_campaign"
    summaries = []
    for directory in sorted(base.iterdir()) if base.exists() else []:
        if not directory.is_dir() or not directory.name.startswith("Ur"):
            continue
        audit = directory / "sdof_audit.csv"
        if audit.is_file():
            try:
                match = re.match(r"Ur([0-9]+p[0-9]+|[0-9]+(?:\.[0-9]+)?)", directory.name)
                if not match:
                    continue
                ur = float(match.group(1).replace("p", "."))
            except ValueError:
                continue
            summaries.append(analyze(audit, ur))
    out = {"campaign": summaries, "reference_note": "Re=100, m*=10, zeta=0.01; this runner is 1DOF transverse, whereas Tang et al. DOI 10.1155/2013/890423 is treated as a 2DOF reference, so exact amplitudes are not claimed."}
    (base / "sdof_campaign_summary.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
