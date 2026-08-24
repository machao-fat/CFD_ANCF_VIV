from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def read(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]


def rms(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / max(1, len(values)))


def time_window(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    selected = [row for row in rows if start <= row["time_s"] <= end]
    if len(selected) < 2:
        raise ValueError(f"not enough samples in window [{start}, {end}]")
    times = [row["time_s"] for row in selected]
    if any(t1 <= t0 for t0, t1 in zip(times, times[1:])):
        raise ValueError("time array is not strictly increasing")
    if abs(times[0] - start) > 1.0e-9 or abs(times[-1] - end) > 1.0e-9:
        raise ValueError(f"window endpoints are not represented: {times[0]} -> {times[-1]}")
    return selected


def mean_time_integral(rows: list[dict[str, float]], key: str) -> float:
    duration = rows[-1]["time_s"] - rows[0]["time_s"]
    if duration <= 0.0:
        raise ValueError("non-positive time-window duration")
    integral = sum(
        0.5 * (rows[i - 1][key] + rows[i][key])
        * (rows[i]["time_s"] - rows[i - 1]["time_s"])
        for i in range(1, len(rows))
    )
    return integral / duration


def sample_dt(rows: list[dict[str, float]]) -> float:
    intervals = [b["time_s"] - a["time_s"] for a, b in zip(rows, rows[1:])]
    return sum(intervals) / len(intervals)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse", type=Path, default=root / "results/04_sdof_viv_campaign/Ur5p2_screen/sdof_audit.csv")
    parser.add_argument("--refined", type=Path, default=root / "results/04_sdof_viv_campaign/Ur5p2_dt2_sameinitial/sdof_audit.csv")
    parser.add_argument("--output", type=Path, default=root / "results/04_time_step_convergence/sdof_ur5p2_dt_comparison.json")
    parser.add_argument("--window-start", type=float, default=5.0)
    parser.add_argument("--window-end", type=float, default=10.0)
    args = parser.parse_args()
    a = time_window(read(args.coarse), args.window_start, args.window_end)
    b = time_window(read(args.refined), args.window_start, args.window_end)

    # Do not force the refined grid onto the coarse grid.  Each trajectory is
    # evaluated on its complete physical-time window.
    metrics: dict[str, object] = {}
    for key in ("y_m", "force_y_N"):
        coarse_values = [row[key] for row in a]
        refined_values = [row[key] for row in b]
        coarse_rms = rms(coarse_values)
        refined_rms = rms(refined_values)
        metrics[key + "_rms_coarse"] = coarse_rms
        metrics[key + "_rms_refined"] = refined_rms
        metrics[key + "_relative_change"] = abs(refined_rms - coarse_rms) / max(coarse_rms, 1.0e-30)

    pa = mean_time_integral(a, "instantaneous_power_W")
    pb = mean_time_integral(b, "instantaneous_power_W")
    metrics.update({
        "mean_power_coarse_W": pa,
        "mean_power_refined_W": pb,
        "mean_power_relative_change": abs(pb - pa) / max(abs(pa), 1.0e-30),
        "coarse_dt_s": sample_dt(a),
        "refined_dt_s": sample_dt(b),
        "physical_window_s": args.window_end - args.window_start,
        "coarse_samples": len(a),
        "refined_samples": len(b),
        "time_arrays_aligned_at_endpoints": abs(a[0]["time_s"] - b[0]["time_s"]) <= 1.0e-12 and abs(a[-1]["time_s"] - b[-1]["time_s"]) <= 1.0e-12,
        "rms_method": "full_window_samples_per_grid",
        "power_method": "trapezoidal_time_integral_per_grid",
        "coarse_window_cycles": (args.window_end - args.window_start) / 5.2,
        "refined_window_cycles": (args.window_end - args.window_start) / 5.2,
        "status": "short_window_time_step_screening_pass_long_window_validation_pending",
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
