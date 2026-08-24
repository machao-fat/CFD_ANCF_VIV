"""Audit existing Ur=5.2 dt and dt/2 runs without overstating their length."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    from .analyze_long_sdof import merge_rows, trap
    from .analyze_response_cycle_aligned_v6 import dft_frequency
except ImportError:
    from analyze_long_sdof import merge_rows, trap
    from analyze_response_cycle_aligned_v6 import dft_frequency


def metric(rows: list[dict[str, float]], start: float, end: float, fn: float) -> dict[str, float]:
    selected = [r for r in rows if start - 1e-12 <= r["time_s"] <= end + 1e-12]
    if len(selected) < 10:
        raise ValueError(f"not enough rows for {start}..{end}")
    times = [r["time_s"] for r in selected]
    y = [r["y_m"] for r in selected]
    fy = [r["force_y_N"] for r in selected]
    cl = [r["Cl"] for r in selected]
    work = trap(selected, "instantaneous_power_W")
    damping = selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"]
    mechanical = selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"]
    energy_residual = work - damping - mechanical
    return {
        "start_s": start, "end_s": end, "samples": len(selected),
        "cycles_at_fn": (end - start) * fn,
        "dt_s": sum(times[i] - times[i - 1] for i in range(1, len(times))) / (len(times) - 1),
        "y_rms_m": math.sqrt(sum(v * v for v in y) / len(y)),
        "half_amplitude_m": 0.5 * (max(y) - min(y)),
        "fy_rms_N": math.sqrt(sum(v * v for v in fy) / len(fy)),
        "Cl_rms": math.sqrt(sum(v * v for v in cl) / len(cl)),
        "primary_frequency_Hz_dft": dft_frequency(y, times),
        "lift_frequency_Hz_dft": dft_frequency(fy, times),
        "mean_power_W": work / (end - start),
        "fluid_work_J": work,
        "damping_dissipation_J": damping,
        "mechanical_energy_change_J": mechanical,
        "energy_residual_J": energy_residual,
        "energy_residual_relative": abs(energy_residual) / max(abs(work), abs(damping), abs(mechanical), 1e-30),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse", type=Path, required=True)
    parser.add_argument("--refined", type=Path, required=True)
    parser.add_argument("--start", type=float, default=5.0)
    parser.add_argument("--end", type=float, default=10.0)
    parser.add_argument("--fn", type=float, default=1.0 / 5.2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    coarse = metric(merge_rows([args.coarse]), args.start, args.end, args.fn)
    refined = metric(merge_rows([args.refined]), args.start, args.end, args.fn)

    def rel(key: str) -> float:
        return abs(refined[key] - coarse[key]) / max(abs(coarse[key]), 1e-30)

    changes = {key: rel(key) for key in ("y_rms_m", "half_amplitude_m", "fy_rms_N", "Cl_rms", "mean_power_W")}
    changes["primary_frequency_Hz_dft"] = rel("primary_frequency_Hz_dft")
    criteria = {
        "displacement_and_force_lt_5pct": all(changes[k] < 0.05 for k in ("y_rms_m", "half_amplitude_m", "fy_rms_N", "Cl_rms")),
        "frequency_lt_2pct": changes["primary_frequency_Hz_dft"] < 0.02,
        "mean_power_lt_10pct": changes["mean_power_W"] < 0.10,
    }
    payload = {
        "scheme": "B_short_window_screening",
        "status": "screening_pass_long_window_validation_pending",
        "same_late_checkpoint_state": False,
        "reason_long_window_scheme_A_not_available": "The existing dt=0.0025 and dt=0.00125 runs start from t=0 and end at 10 s; the common comparison interval is only 0.9615 fn cycles, not the required 3-5 response cycles from a common late CFD/structure checkpoint.",
        "window_s": [args.start, args.end],
        "natural_frequency_Hz": args.fn,
        "coarse_dt_s": 0.0025,
        "refined_dt_s": 0.00125,
        "coarse": coarse,
        "refined": refined,
        "relative_changes": changes,
        "criteria": criteria,
        "screening_pass": all(criteria.values()),
        "formal_long_window_gate": False,
        "required_follow_up": "Run scheme A from the same late Ur=5.2 CFD and structure state for at least 3, preferably 5, full measured response cycles before declaring formal long-window convergence.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
