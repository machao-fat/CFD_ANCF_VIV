from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.convergence_observability_v1 import ConvergenceAccumulator, StepObservation  # noqa: E402


SEGMENTS = (
    ROOT / "runtime/294_cpp_worker_precice_three_slice_10s_v1/slice_0000/postProcessing/forces1/0/forces.dat",
    ROOT / "runtime/295_cpp_worker_precice_three_slice_continue20s_v1/slice_0000/postProcessing/forces1/10/forces.dat",
    ROOT / "runtime/297_cpp_worker_precice_three_slice_continue40s_v1/slice_0000/postProcessing/forces1/30/forces.dat",
    ROOT / "runtime/298_cpp_worker_precice_three_slice_to125s_v1/slice_0000/postProcessing/forces1/70/forces.dat",
)
SLICES = ("slice_0000", "slice_0001", "slice_0002")


def read_forces(path: Path) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    pattern = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s+\(\((.*?)\)\s+\((.*?)\)")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        values_a = [float(value) for value in re.findall(r"[-+0-9.eE]+", match.group(2))]
        values_b = [float(value) for value in re.findall(r"[-+0-9.eE]+", match.group(3))]
        if len(values_a) >= 3 and len(values_b) >= 3:
            rows.append((float(match.group(1)), values_a[1] + values_b[1]))
    return rows


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zero_crossing_frequency(samples: list[dict[str, object]]) -> float | None:
    if len(samples) < 3:
        return None
    values = [float(item["force_y"]) for item in samples]
    mean = sum(values) / len(values)
    crossings = sum(1 for left, right in zip(values, values[1:]) if (left - mean) * (right - mean) < 0.0)
    duration = float(samples[-1]["time_s"]) - float(samples[0]["time_s"])
    return crossings / (2.0 * duration) if duration > 0.0 and crossings >= 2 else None


def main() -> int:
    rows: dict[float, float] = {}
    for path in SEGMENTS:
        if not path.is_file():
            raise SystemExit(f"missing force evidence: {path}")
        for time_s, force_y in read_forces(path):
            rows.setdefault(time_s, force_y)
    accumulator = ConvergenceAccumulator(dt_s=0.005, slice_ids=SLICES, sample_every_steps=1)
    for time_s in sorted(rows):
        step = int(round(time_s / 0.005))
        if step < 1:
            continue
        accumulator.observe(StepObservation(
            global_step=step, case_local_bridge_step=step, time_s=time_s,
            integer_tick=int(round(time_s * 1.0e9)),
            slice_force_y={sid: rows[time_s] for sid in SLICES},
        ))
    result = accumulator.finalize()
    result["stage_id"] = "stage4f_d_convergence_observability_v1"
    result["source_stage"] = "294+295+297+298"
    result["source_files"] = [{"path": str(path), "sha256": sha256(path)} for path in SEGMENTS]
    result["zero_crossing_frequency_hz"] = zero_crossing_frequency(accumulator._samples)
    result["fft_frequency_hz"] = result.get("fft_frequency_hz")
    zero = result["zero_crossing_frequency_hz"]
    fft = result["fft_frequency_hz"]
    if zero is None or fft is None:
        result["reasons"].append("FFT/zero-crossing frequency comparison is unavailable")
    elif abs(fft - zero) / max(abs(fft), abs(zero), 1.0e-30) > 0.05:
        result["reasons"].append("FFT and zero-crossing frequencies differ by more than 5%")
    result["criteria"] = {
        "minimum_valid_cycles": 15,
        "minimum_scalar_samples": 300,
        "stable_window_count": 3,
        "frequency_difference_tolerance": 0.05,
        "amplitude_drift_tolerance": 0.05,
        "pimple_residual_courant_continuity": "not_recorded_in_stage298",
        "virtual_work_force_moment": "not_recorded_in_stage298",
    }
    result["real_process_counts"] = {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0}
    result["storage_plan"] = {
        "force_observables": "one scalar row per 0.05 s, aggregated across slices",
        "worker_quality": "one scalar summary per 100 global steps",
        "cycle_events": "one row per accepted peak/period",
        "openfoam_quality": "one compact row per CFD time step; no full stdout retention",
        "fields": "purgeWrite=1 plus source and final restart only",
    }
    out = ROOT / "results/299_convergence_observability_v1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "stage4f_d_convergence_observability_v1_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"formal_convergence": result["formal_convergence"], "sample_count": result["sample_count"], "cycle_count": result["cycle_count"], "reasons": result["reasons"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
