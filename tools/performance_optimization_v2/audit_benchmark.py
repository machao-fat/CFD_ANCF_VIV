from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v2.attribution import attribute_measurements
from coupling.performance_optimization_v2.matrix import required_matrix, validate_matrix
from coupling.performance_optimization_v2.telemetry import StepTiming, TelemetryError, summarize_timings, validate_source_mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Stage95 real benchmark evidence; never starts a process.")
    parser.add_argument("--input", required=True, help="JSON object keyed by B/M/.../FINAL; each value is evidence or repeat list")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out = Path(args.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    errors: list[str] = []
    try:
        validate_matrix(key for key in source if key not in {"FINAL_FACTORS", "metadata"})
        attribution = attribute_measurements(source).to_dict()
    except Exception as exc:
        errors.append(f"attribution:{exc}"); attribution = None
    phase_records: dict[str, object] = {}
    for label, raw in source.items():
        if label in {"FINAL_FACTORS", "metadata"}: continue
        samples = raw if isinstance(raw, list) else [raw]
        for index, sample in enumerate(samples):
            if not isinstance(sample, dict) or "step_records" not in sample:
                errors.append(f"{label}[{index}]:missing step_records"); continue
            try:
                records = [StepTiming.from_dict(item) for item in sample["step_records"]]
                metadata = source.get("metadata", {})
                if not all(field in metadata for field in ("source_global_step", "source_time_s", "source_tick", "global_dt_s")):
                    raise TelemetryError("source mapping metadata is missing")
                validate_source_mapping(records, source_global_step=int(metadata["source_global_step"]),
                                        source_time_s=float(metadata["source_time_s"]),
                                        source_tick=int(metadata["source_tick"]),
                                        dt_s=float(metadata["global_dt_s"]))
                summary = summarize_timings(records)
                if summary["steps"] != 40: errors.append(f"{label}[{index}]:expected 40 steps")
                if sample.get("external_process_starts_by_codex", 0) != 0 and sample.get("launch_mode") != "codex_direct":
                    errors.append(f"{label}[{index}]:external process ownership is not auditable")
                launch_mode = sample.get("launch_mode", "user_session_runner")
                if launch_mode not in {"codex_direct", "user_session_runner"}:
                    errors.append(f"{label}[{index}]:unsupported launch_mode={launch_mode}")
                if sample.get("requires_user_session_runner") and sample.get("error_classification") != "matlab_applicationservice_5001":
                    errors.append(f"{label}[{index}]:runner fallback requested without explicit 5001 evidence")
                if sample.get("owned_residual", 0) != 0:
                    errors.append(f"{label}[{index}]:owned residual is nonzero")
                if sample.get("persistent_ipc_requested", False):
                    if not sample.get("persistent_ipc", False):
                        errors.append(f"{label}[{index}]:persistent IPC was requested but not actually integrated")
                    if sample.get("persistent_ipc_mode") == "legacy_file_bridge_unchanged":
                        errors.append(f"{label}[{index}]:legacy file bridge cannot substantiate persistent IPC")
                phase_records[f"{label}_{index}"] = summary
            except (TelemetryError, TypeError, ValueError, KeyError) as exc:
                errors.append(f"{label}[{index}]:{exc}")
    metadata = source.get("metadata", {})
    real = bool(metadata.get("real_measurement", False))
    required_metadata = ("source_global_step", "source_time_s", "source_tick", "global_dt_s", "source_checkpoint_sha256")
    for field in required_metadata:
        if field not in metadata:
            errors.append(f"metadata:{field} missing")
    baseline = None if attribution is None else attribution["baseline_median_s"]
    final = None if attribution is None else attribution["final_median_s"]
    repeatability = {}
    if "FINAL" in source and isinstance(source["FINAL"], list) and source["FINAL"]:
        values = [float(item.get("wall_clock_s", item.get("segment_wall_clock_s"))) for item in source["FINAL"]]
        repeatability = {"samples_s": values, "median_s": statistics.median(values), "relative_range": (max(values) - min(values)) / statistics.median(values)}
        if repeatability["relative_range"] > .10: errors.append("FINAL repeatability exceeds 10%")
    gate = {"gate": "STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: pass" if real and not errors and baseline is not None and final is not None and final <= 600 and baseline / final >= 1.5 else "STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: do_not_pass",
            "real_measurement": real, "baseline_median_s": baseline, "final_median_s": final,
            "speedup": (baseline / final if baseline and final else None), "errors": errors,
            "external_process_starts_by_codex": 0, "scope_expansion": False,
            "physical_contract_modified": False, "numerical_contract_modified": False,
            "formal_protocol_semantics_modified": False, "old_evidence_modified": False,
            "statistics_status": {"frequency": "not_evaluable_performance_optimization_only", "FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"}}
    files = {"optimization_factor_measurements.json": source, "optimization_weight_attribution.json": attribution or {"status": "not_available", "errors": errors},
             "optimization_ablation_matrix.json": {"required": [item.__dict__ for item in required_matrix()], "observed_labels": [key for key in source if key not in {"FINAL_FACTORS", "metadata"}]},
             "real_phase_timing_baseline.json": {key: value for key, value in phase_records.items() if key.startswith("B_")},
             "real_phase_timing_optimized.json": {key: value for key, value in phase_records.items() if key.startswith("FINAL_")},
             "resource_usage_comparison.json": {"source": source.get("metadata", {}).get("resources", {})},
             "repeatability_audit.json": repeatability,
             "stage4f_d_solver_performance_optimization_v2_gate.json": gate}
    for name, value in files.items(): (out / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=True))
    return 0 if gate["gate"] == "STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: pass" else 2


if __name__ == "__main__": raise SystemExit(main())
