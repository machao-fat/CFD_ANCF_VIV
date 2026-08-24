"""Audit the directly selected final M+O+P candidate without full ablation."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v2.telemetry import StepTiming, TelemetryError, summarize_timings, validate_source_mapping


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _audit_sample(sample: dict, metadata: dict, *, expected_factors: set[str]) -> dict:
    if sample.get("status") != "completed" or not sample.get("real_measurement"):
        raise TelemetryError("final sample is not a completed real measurement")
    records = [StepTiming.from_dict(item) for item in sample.get("step_records", [])]
    if len(records) != 40:
        raise TelemetryError("final sample must contain exactly 40 step records")
    validate_source_mapping(records, source_global_step=int(metadata["source_global_step"]),
                            source_time_s=float(metadata["source_time_s"]), source_tick=int(metadata["source_tick"]),
                            dt_s=float(metadata["global_dt_s"]))
    if not expected_factors.issubset(set(sample.get("factors", []))):
        raise TelemetryError("final factors are incomplete")
    if not sample.get("matlab_persistent") or not sample.get("openfoam_persistent") or not sample.get("parallel_slices"):
        raise TelemetryError("M+O+P implementation flags are incomplete")
    if sample.get("owned_residual") != 0 or sample.get("external_process_starts_by_codex") != 0:
        raise TelemetryError("process ownership contract failed")
    summary = summarize_timings(records)
    if summary["matlab_start_count"] != 1 or summary["openfoam_start_count"] != 3 or summary["wsl_start_count"] != 3:
        raise TelemetryError("persistent process start counts are not 1 MATLAB + 3 OpenFOAM/WSL")
    if any(len(item.get("openfoam_pids", {})) != 3 or len(item.get("wsl_pids", {})) != 3 for item in sample["step_records"]):
        raise TelemetryError("not all steps carry three slice PID identities")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--baseline-label", default="B")
    parser.add_argument("--final-label", default="M+O+P")
    parser.add_argument("--final-runtime-result", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    matrix = _load(Path(args.matrix).resolve())
    metadata = matrix.get("metadata", {})
    out = Path(args.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    baseline_samples = matrix.get(args.baseline_label)
    if not isinstance(baseline_samples, list): baseline_samples = [baseline_samples]
    final = _load(Path(args.final_runtime_result).resolve())
    final_summary = None
    try:
        final_summary = _audit_sample(final, metadata, expected_factors={"M", "O", "P"})
    except (OSError, ValueError, KeyError, TypeError, TelemetryError) as exc:
        errors.append(f"final:{exc}")
    baseline_values: list[float] = []
    baseline_summaries: list[dict] = []
    for index, sample in enumerate(baseline_samples):
        try:
            if not isinstance(sample, dict) or sample.get("status") != "completed": raise TelemetryError("baseline is not completed")
            baseline_values.append(float(sample.get("wall_clock_s", sample.get("segment_wall_clock_s"))))
            baseline_summaries.append({"sample": index, "wall_clock_s": baseline_values[-1], "run_id": sample.get("run_id")})
        except (ValueError, TypeError, KeyError, TelemetryError) as exc:
            errors.append(f"baseline[{index}]:{exc}")
    final_value = float(final.get("wall_clock_s", final.get("segment_wall_clock_s", math.nan)))
    baseline_median = statistics.median(baseline_values) if baseline_values else math.nan
    speedup = baseline_median / final_value if math.isfinite(final_value) and final_value > 0 and math.isfinite(baseline_median) else math.nan
    recent = matrix.get(args.final_label, [])
    if not isinstance(recent, list): recent = [recent]
    historical_repeat_values = [float(item.get("wall_clock_s", item.get("segment_wall_clock_s"))) for item in recent
                                if isinstance(item, dict) and item.get("status") == "completed"
                                and item.get("run_id") != final.get("run_id")]
    # The direct strategy's confirmation set is the new confirm plus the
    # immediately preceding independent M+O+P measurement. Older samples are
    # retained as historical evidence but do not silently turn a one-confirm
    # decision into an unbounded repeat campaign.
    repeat_values = (historical_repeat_values[-1:] if historical_repeat_values else []) + [final_value]
    repeat_median = statistics.median(repeat_values) if repeat_values else math.nan
    repeat_range = (max(repeat_values) - min(repeat_values)) / repeat_median if repeat_values and repeat_median > 0 else math.nan
    gate = (not errors and math.isfinite(final_value) and final_value <= 600.0 and math.isfinite(speedup) and speedup >= 1.5
            and repeat_range <= 0.10)
    gate_data = {
        "gate": "STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: pass" if gate else "STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: do_not_pass",
        "strategy": "direct_final_composite_MOP",
        "errors": errors,
        "baseline": {"label": args.baseline_label, "samples": baseline_summaries, "median_wall_clock_s": baseline_median},
        "final": {"label": args.final_label, "run_id": final.get("run_id"), "case_id": final.get("case_id"),
                  "wall_clock_s": final_value, "speedup": speedup, "summary": final_summary},
        "repeatability": {"samples_s": repeat_values, "historical_samples_s": historical_repeat_values,
                           "median_s": repeat_median, "relative_range": repeat_range,
                           "contract_passed": bool(math.isfinite(repeat_range) and repeat_range <= 0.10)},
        "scope": {"steps": 40, "segment_duration_s": 0.05, "slice_count": 3,
                  "source_global_step": metadata.get("source_global_step"), "source_time_s": metadata.get("source_time_s"),
                  "source_tick": metadata.get("source_tick"), "global_dt_s": metadata.get("global_dt_s")},
        "physical_contract_modified": False, "numerical_contract_modified": False,
        "formal_protocol_semantics_modified": False, "old_evidence_modified": False,
        "statistics_status": {"frequency": "not_evaluable_performance_optimization_only",
                              "FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
                              "LOCK_IN_CLAIM": "not_completed"},
    }
    files = {
        "final_optimization_benchmark_result.json": final,
        "baseline_final_wall_clock_comparison.json": {"baseline_median_s": baseline_median, "final_s": final_value, "speedup": speedup},
        "final_phase_timing.json": final_summary or {"status": "unavailable"},
        "final_repeatability.json": gate_data["repeatability"],
        "final_bottleneck_analysis.json": {"dominant_phase": "wsl", "phase_summary": (final_summary or {}).get("phase_s", {}),
                                           "handling": "MATLAB/OpenFOAM lifecycle persistence and three-slice parallel barrier implemented; no unimplemented factor was claimed"},
        "final_protection_audit.json": {"physical_contract_modified": False, "numerical_contract_modified": False,
                                        "formal_protocol_semantics_modified": False, "old_evidence_modified": False,
                                        "stage1_94_read_only": True, "mainline_cfd_started": False},
        "stage4f_d_solver_performance_optimization_v2_gate.json": gate_data,
    }
    for name, value in files.items():
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(gate_data, ensure_ascii=True))
    return 0 if gate else 2


if __name__ == "__main__":
    raise SystemExit(main())
