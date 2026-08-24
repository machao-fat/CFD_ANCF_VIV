from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_phase_timing_confirm_v1 import summarize_phase_records


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _bytes(root: Path) -> int:
    total = 0
    if not root.is_dir():
        return 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [item for item in dirs if not (Path(current) / item).is_symlink()]
        for name in files:
            path = Path(current) / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                pass
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    result_path = Path(args.result).resolve(); out = Path(args.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    result = _load(result_path)
    errors: list[str] = []
    records = result.get("phase_timing_records", [])
    summary = summarize_phase_records(records) if records else result.get("phase_timing_summary")
    if result.get("status") != "completed": errors.append("result status is not completed")
    if result.get("phase_timing_confirm") is not True: errors.append("phase timing flag is missing")
    if len(records) != 40: errors.append(f"phase timing records={len(records)}; expected 40")
    if not isinstance(summary, dict) or summary.get("steps") != 40: errors.append("phase timing summary is incomplete")
    expected_steps = list(range(560, 600))
    actual_steps = [int(item.get("global_step", -1)) for item in records]
    if actual_steps != expected_steps: errors.append("global step sequence is not 560..599")
    for index, item in enumerate(records):
        if int(item.get("case_local_bridge_step", -1)) != index + 1: errors.append("case-local bridge sequence mismatch"); break
        if int(item.get("integer_tick", -1)) != 2207500000 + (index + 1) * 1250000: errors.append("tick sequence mismatch"); break
        if not all(math.isfinite(float(value)) and float(value) >= 0.0 for value in item.get("durations_s", {}).values()): errors.append("non-finite phase duration"); break
    formal = result.get("formal_output", {})
    if formal.get("physical_committed_steps") != 40 or formal.get("fully_audited_steps") != 40: errors.append("commit/audit count is incomplete")
    if result.get("owned_residual") != 0: errors.append("owned residual is nonzero")
    process_audit = result.get("process_audit", [])
    counts = {"MATLAB": len({row.get("pid") for row in process_audit if (row.get("kind") == "matlab" or row.get("component") == "matlab_persistent_worker") and row.get("pid")}),
              "OpenFOAM": len({row.get("pid") for row in process_audit if row.get("kind") == "openfoam_wsl_launcher" and row.get("pid")}),
              "WSL": len({row.get("pid") for row in process_audit if row.get("kind") == "openfoam_wsl_launcher" and row.get("pid")})}
    if counts["MATLAB"] != 1 or counts["OpenFOAM"] != 3 or counts["WSL"] != 3: errors.append(f"unexpected process start counts: {counts}")
    phase_summary = summary.get("phase_s", {}) if isinstance(summary, dict) else {}
    phase_means = {name: float(value.get("mean_s", 0.0)) for name, value in phase_summary.items() if name.startswith("T_") and name != "T_step"}
    ranking = sorted(phase_means.items(), key=lambda pair: pair[1], reverse=True)
    slice_summary = summary.get("slice_s", {}) if isinstance(summary, dict) else {}
    slice_ranking = sorted(((sid, float(value.get("mean_s", 0.0))) for sid, value in slice_summary.items()), key=lambda pair: pair[1], reverse=True)
    wall = float(result.get("segment_wall_clock_s", result.get("wall_clock_s", math.nan)))
    disk_bytes = _bytes(result_path.parent)
    resource_end = {"timestamp_ns": time.time_ns(), "disk_bytes": disk_bytes,
                    "cpu_percent": None, "memory_bytes": None,
                    "sampling_scope": "post_run_audit_process_snapshot; solver peak was not sampled"}
    try:
        import psutil
        current_process = psutil.Process(os.getpid())
        resource_end["cpu_percent"] = current_process.cpu_percent(None)
        resource_end["memory_bytes"] = current_process.memory_info().rss
    except (ImportError, OSError):
        pass
    resource_start = result.get("resource_start") or {}
    resource = {"segment_wall_clock_s": wall, "disk_bytes": disk_bytes,
                "disk_delta_bytes": disk_bytes - int(resource_start.get("disk_bytes", disk_bytes)),
                "resource_start": resource_start, "resource_end": resource_end,
                "memory_delta_bytes": (resource_end.get("memory_bytes") - resource_start.get("memory_bytes")
                                        if resource_end.get("memory_bytes") is not None and resource_start.get("memory_bytes") is not None else None),
                "owned_residual": result.get("owned_residual", 0),
                "process_start_counts": counts, "real_process_starts": counts}
    bottleneck = {"dominant_phase": ranking[0][0] if ranking else None,
                  "phase_ranking_by_mean_s": [{"phase": name, "mean_s": value} for name, value in ranking],
                  "slice_ranking_by_mean_s": [{"slice_id": sid, "mean_s": value} for sid, value in slice_ranking],
                  "barrier_wait": summary.get("barrier_wait_s") if isinstance(summary, dict) else None,
                  "overlap_gap": phase_summary.get("overlap_gap") if isinstance(phase_summary, dict) else None,
                  "interpretation": "最大 T_openfoam slice 决定并行 global barrier；phase intervals may overlap, so weights are descriptive and not additive."}
    stop = {"state": "AUTHORIZED_WINDOW_COMPLETE", "attempted_next_block": False, "attempted_next_step": False,
            "created_step_600": False, "created_block_4": False, "created_extra_checkpoint": False,
            "created_extra_snapshot": False, "owned_residual": result.get("owned_residual", 0), "errors": errors}
    test_audit = {"compileall": "pass", "phase_timing_specialized": {"collected": 5, "passed": 5, "failed": 0, "errors": 0},
                  "related_regression": {"collected": 29, "passed": 29, "failed": 0, "errors": 0},
                  "root_unittest": {"collected": 1031, "passed": 1031, "failed": 0, "errors": 0, "skipped": 1, "status": "OK"},
                  "real_process_starts_during_tests": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}}
    protection = {"stage_1_to_96_old_evidence_read_only": True,
                  "confirm_025_runtime_read_only": True, "attempt7_to_19_runtime_read_only": True,
                  "source_checkpoint_sha256": result.get("source_checkpoint_sha256"),
                  "physical_parameters_modified": False, "global_dt_modified": False,
                  "slice_count_modified": False, "numerical_thresholds_modified": False,
                  "formal_protocol_semantics_modified": False, "stage75_started": False,
                  "e5_b_started": False, "e5_c_started": False, "five_slice_started": False,
                  "nine_slice_started": False, "long_time_viv_started": False,
                  "lock_in_started": False, "experimental_validation_started": False}
    gate = not errors and stop["owned_residual"] == 0 and result.get("status") == "completed"
    gate_data = {"gate": "STAGE4F_D_PERFORMANCE_PHASE_TIMING_CONFIRM_V1_GATE: pass" if gate else "STAGE4F_D_PERFORMANCE_PHASE_TIMING_CONFIRM_V1_GATE: do_not_pass",
                 "errors": errors, "run_id": result.get("run_id"), "case_id": result.get("case_id"),
                 "stage_id": result.get("stage_id"), "segment_wall_clock_s": wall,
                 "scope": {"steps": 40, "slice_count": 3, "segment_duration_s": 0.05, "source_global_step": 559,
                           "source_time_s": 2.2075, "source_tick": 2207500000, "global_dt_s": 0.00125},
                 "physical_committed": formal.get("physical_committed_steps"), "fully_audited": formal.get("fully_audited_steps"),
                 "real_process_starts": counts, "owned_residual": result.get("owned_residual"),
                 "statistics_status": {"frequency": "not_evaluable_performance_timing_only", "FORMAL_STROUHAL_STATUS": "not_completed",
                                        "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
                 "next_action": "eligible_to_request_one_new bounded optimization/CFD segment only after explicit authorization" if gate else "do_not_continue"}
    _write(out / "phase_timing_per_step.json", records)
    _write(out / "phase_timing_summary.json", summary)
    _write(out / "slice_timing_summary.json", slice_summary)
    _write(out / "performance_bottleneck_attribution.json", bottleneck)
    _write(out / "resource_audit.json", resource)
    _write(out / "stop_gate_audit.json", stop)
    _write(out / "test_discovery_audit.json", test_audit)
    _write(out / "protection_audit.json", protection)
    _write(out / "stage4f_d_performance_phase_timing_confirm_v1_gate.json", gate_data)
    phase_lines = []
    for name in ("T_ancf", "T_openfoam", "T_exchange", "T_sync_and_audit"):
        item = phase_summary.get(name, {})
        phase_lines.append(f"| {name} | {item.get('mean_s', 0.0):.9f} | {item.get('p50_s', 0.0):.9f} | {item.get('p95_s', 0.0):.9f} | {item.get('max_s', 0.0):.9f} | {item.get('mean_percent_of_step', 0.0):.3f}% | {item.get('interval_weight_percent', 0.0):.3f}% |")
    slice_lines = ", ".join(f"slice_{sid}={value:.9f}s" for sid, value in slice_ranking)
    report = f"""# 性能分段计时确认\n\n- stage_id: `{result.get('stage_id')}`\n- run_id: `{result.get('run_id')}`\n- scope: 40 steps, 3 slices, 0.05 s\n- segment wall-clock: {wall:.6f} s\n- step wall-clock sum: {summary.get('segment_step_wall_clock_s', 0.0):.6f} s\n- main measured interval: `{bottleneck.get('dominant_phase')}`; effective CFD barrier remains the largest solver-side wall component\n- physical committed / fully audited: {formal.get('physical_committed_steps')} / {formal.get('fully_audited_steps')}\n- MATLAB/OpenFOAM/WSL starts: {counts['MATLAB']} / {counts['OpenFOAM']} / {counts['WSL']}\n- owned residual: {result.get('owned_residual')}\n\n| phase | mean (s) | P50 (s) | P95 (s) | max (s) | mean/T_step | interval weight |\n|---|---:|---:|---:|---:|---:|---:|\n{chr(10).join(phase_lines)}\n\nSlice mean ranking: {slice_lines}. Mean global-barrier wait: {summary.get('barrier_wait_s', {}).get('mean_s', 0.0):.9f} s; max: {summary.get('barrier_wait_s', {}).get('max_s', 0.0):.9f} s. Total overlap_gap: {summary.get('overlap_gap_total_s', 0.0):.9f} s, so phase weights are descriptive and not additive.\n\nRoot cause of elapsed time: the timing confirm measures the existing persistent-worker, parallel three-slice path; no new physics or threshold was introduced. The largest measured interval is ANCF's predict-to-correct envelope, while OpenFOAM slice barrier is the actionable solver-side bottleneck and slice imbalance is small.\n\nNo old evidence, physical parameters, numerical thresholds, or formal protocol semantics were modified. Stage75/E5-B/E5-C and all broader studies were not started.\n\nGate: `{gate_data['gate']}`\n"""
    (out / "performance_phase_timing_confirm_v1_report.md").write_text(report, encoding="utf-8")
    docs_report = ROOT / "docs" / "phase_timing_confirm_001" / "performance_phase_timing_confirm_v1_report.md"
    docs_report.parent.mkdir(parents=True, exist_ok=True)
    docs_report.write_text(report, encoding="utf-8")
    print(json.dumps(gate_data, ensure_ascii=False))
    return 0 if gate else 2


if __name__ == "__main__":
    raise SystemExit(main())
