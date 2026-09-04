#!/usr/bin/env python3
"""Fail-closed Stage 2 OpenFOAM--Fluent prescribed-motion comparison."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
COMPONENTS = ("Fx_N", "Fy_N", "Mz_Nm")


def fluent_rows(root: Path, name: str) -> dict[int, float]:
    values: dict[int, float] = {}
    for line in (root / name).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            step, value, time = (float(x) for x in line.split())
        except ValueError:
            continue
        index = int(round(time / 0.0025))
        if index in values:
            raise ValueError(f"Fluent {name}: duplicate step {index}")
        values[index] = value
    return values


def of_rows(paths: list[Path]) -> dict[int, tuple[float, float, float]]:
    values: dict[int, tuple[float, float, float]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            numbers = [float(x) for x in NUMBER.findall(line)]
            if len(numbers) != 13:
                continue
            time = numbers[0]
            fx = numbers[1] + numbers[4]
            fy = numbers[2] + numbers[5]
            mz = numbers[9] + numbers[12]
            index = int(round(time / 0.0025))
            row = (fx, fy, mz)
            if index in values:
                if any(abs(a - b) > 1e-8 for a, b in zip(values[index], row)):
                    raise ValueError(f"OpenFOAM forces: inconsistent duplicate at step {index}")
            else:
                values[index] = row
    return values


def finite(sequence: list[float]) -> bool:
    return all(math.isfinite(x) for x in sequence)


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def rms_about_mean(values: list[float]) -> float:
    mu = mean(values)
    return math.sqrt(sum((x - mu) ** 2 for x in values) / len(values))


def correlation(a: list[float], b: list[float]) -> float | None:
    ma, mb = mean(a), mean(b)
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    return None if sa == 0 or sb == 0 else sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def spectral_peak(values: list[float], times: list[float]) -> float:
    centred = [x - mean(values) for x in values]
    best_frequency, best_power = 0.05, -1.0
    for k in range(50, 501):
        f = k / 1000.0
        re = sum(y * math.cos(2.0 * math.pi * f * t) for y, t in zip(centred, times))
        im = sum(y * math.sin(2.0 * math.pi * f * t) for y, t in zip(centred, times))
        power = re * re + im * im
        if power > best_power:
            best_frequency, best_power = f, power
    return best_frequency


def phase_at(values: list[float], times: list[float], frequency: float) -> float:
    centred = [x - mean(values) for x in values]
    sine = sum(y * math.sin(2.0 * math.pi * frequency * t) for y, t in zip(centred, times))
    cosine = sum(y * math.cos(2.0 * math.pi * frequency * t) for y, t in zip(centred, times))
    return math.atan2(cosine, sine)


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fluent-root", type=Path, required=True)
    p.add_argument("--openfoam-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--window-start", type=float, default=5.0)
    p.add_argument("--window-end", type=float, default=20.0)
    p.add_argument("--motion-frequency", type=float, default=0.16)
    args = p.parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {args.output_dir}")
    force_paths = [args.openfoam_root / "postProcessing/cylinderForces/0/forces.dat", args.openfoam_root / "postProcessing/cylinderForces/0.0125/forces.dat"]
    if not all(path.is_file() for path in force_paths):
        raise SystemExit("missing OpenFOAM force segment")
    fluent = [fluent_rows(args.fluent_root, n) for n in ("drag-force-rfile.out", "lift-force-rfile.out", "moment-z-rfile.out")]
    openfoam = of_rows(force_paths)
    expected = list(range(8001))
    if any(sorted(series) != expected for series in fluent) or sorted(openfoam) != expected:
        raise SystemExit("incomplete or discontinuous time axis")
    times = [i * 0.0025 for i in expected]
    of_values = [[openfoam[i][j] for i in expected] for j in range(3)]
    fl_values = [[series[i] for i in expected] for series in fluent]
    if not all(finite(s) for s in of_values + fl_values):
        raise SystemExit("non-finite force value")
    indices = [i for i, t in enumerate(times) if args.window_start <= t <= args.window_end]
    wt = [times[i] for i in indices]
    report: dict[str, object] = {
        "gate_id": "STAGE2_CROSS_SOLVER_PRESCRIBED_MOTION_COMPARISON",
        "status": "COMPLETED_REVIEW_REQUIRED",
        "motion_contract": {"amplitude_m": 0.1, "frequency_hz": args.motion_frequency, "dt_s": 0.0025},
        "window_s": [args.window_start, args.window_end],
        "samples": {"full": len(times), "window": len(wt)},
        "components": {},
        "notes": ["The 0--5 s startup segment is excluded from statistics.", "No acceptance threshold was pre-authorized; numerical agreement requires review rather than automatic pass/fail."],
    }
    for name, of_all, fl_all in zip(COMPONENTS, of_values, fl_values):
        of = [of_all[i] for i in indices]
        fl = [fl_all[i] for i in indices]
        of_rms, fl_rms = rms_about_mean(of), rms_about_mean(fl)
        nrmse = math.sqrt(sum((a - b) ** 2 for a, b in zip(fl, of)) / len(of)) / of_rms if of_rms else None
        phase_of = phase_at(of, wt, args.motion_frequency)
        phase_fl = phase_at(fl, wt, args.motion_frequency)
        delta = wrap(phase_fl - phase_of)
        report["components"][name] = {
            "openfoam": {"mean": mean(of), "rms_about_mean": of_rms, "peak_to_peak": max(of) - min(of), "dominant_frequency_hz": spectral_peak(of, wt), "phase_at_motion_frequency_rad": phase_of},
            "fluent": {"mean": mean(fl), "rms_about_mean": fl_rms, "peak_to_peak": max(fl) - min(fl), "dominant_frequency_hz": spectral_peak(fl, wt), "phase_at_motion_frequency_rad": phase_fl},
            "correlation": correlation(of, fl),
            "nrmse_relative_to_openfoam_rms": nrmse,
            "fluent_minus_openfoam_phase_rad": delta,
            "fluent_lead_positive_time_s": delta / (2.0 * math.pi * args.motion_frequency),
        }
    args.output_dir.mkdir()
    (args.output_dir / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (args.output_dir / "aligned_forces.csv").open("w", encoding="utf-8") as out:
        out.write("time_s,of_fx_N,fl_fx_N,of_fy_N,fl_fy_N,of_mz_Nm,fl_mz_Nm\n")
        for t, ofx, flx, ofy, fly, ofm, flm in zip(times, of_values[0], fl_values[0], of_values[1], fl_values[1], of_values[2], fl_values[2]):
            out.write(f"{t:.10g},{ofx:.16g},{flx:.16g},{ofy:.16g},{fly:.16g},{ofm:.16g},{flm:.16g}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
