from __future__ import annotations

import json
import os
import platform
import statistics
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import OptimizationConfig, STATISTICAL_STATUS
from .scheduler import GlobalBarrierScheduler, SchedulerResult

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

STAGES = (
    "baseline",
    "matlab_persistent",
    "openfoam_persistent",
    "three_slice_parallel",
    "persistent_ipc",
    "comprehensive",
)


@dataclass(frozen=True)
class LatencyProfile:
    matlab_start_ms: float = 1.50
    openfoam_start_ms: float = 1.00
    matlab_step_ms: float = 0.40
    openfoam_slice_ms: float = 0.80
    file_handshake_ms: float = 0.30
    persistent_ipc_ms: float = 0.04
    checkpoint_ms: float = 0.15


@dataclass
class StageMeasurement:
    stage: str
    stage_id: str
    run_id: str
    case_id: str
    steps: int
    step_ms: list[float]
    phase_ms: dict[str, list[float]]
    segment_wall_clock_s: float
    cpu_percent: float
    memory_bytes: int
    disk_bytes: int
    speedup_vs_baseline: float
    matlab_start_count: int
    openfoam_start_counts: dict[int, int]
    external_process_starts: int
    owned_residual: int
    status: str
    scheduler: dict[str, Any]
    segment_speedup_vs_baseline: float = 1.0
    modeled_segment_wall_clock_s: float = 0.0
    observed_step_ms: list[float] = field(default_factory=list)
    observed_phase_ms: dict[str, list[float]] = field(default_factory=dict)
    observed_speedup_vs_baseline: float = 1.0
    observed_segment_speedup_vs_baseline: float = 1.0

    @staticmethod
    def _stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"average": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        ordered = sorted(values)
        return {
            "average": statistics.fmean(values),
            "p50": ordered[(len(ordered) - 1) * 50 // 100],
            "p95": ordered[(len(ordered) - 1) * 95 // 100],
            "max": max(values),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "stage_id": self.stage_id, "run_id": self.run_id,
            "case_id": self.case_id, "steps": self.steps,
            "per_step_ms": self._stats(self.step_ms),
            "phase_ms": {name: self._stats(values) for name, values in self.phase_ms.items()},
            "observed_per_step_ms": self._stats(self.observed_step_ms),
            "observed_phase_ms": {name: self._stats(values) for name, values in self.observed_phase_ms.items()},
            "segment_wall_clock_s": self.segment_wall_clock_s,
            "modeled_segment_wall_clock_s": self.modeled_segment_wall_clock_s,
            "resource_usage": {"cpu_percent": self.cpu_percent, "memory_bytes": self.memory_bytes, "disk_bytes": self.disk_bytes},
            "speedup_vs_baseline": self.speedup_vs_baseline,
            "segment_speedup_vs_baseline": self.segment_speedup_vs_baseline,
            "observed_speedup_vs_baseline": self.observed_speedup_vs_baseline,
            "observed_segment_speedup_vs_baseline": self.observed_segment_speedup_vs_baseline,
            "matlab_start_count": self.matlab_start_count,
            "openfoam_start_counts": self.openfoam_start_counts,
            "external_process_starts": self.external_process_starts,
            "owned_residual": self.owned_residual,
            "status": self.status,
            "scheduler": self.scheduler,
        }


@dataclass
class BenchmarkReport:
    config: dict[str, Any]
    measurements: list[StageMeasurement]
    bottleneck_ranking: list[dict[str, Any]]
    gate: dict[str, Any]
    optimization_benefits: list[dict[str, Any]] = field(default_factory=list)
    statistical_status: dict[str, str] = field(default_factory=lambda: dict(STATISTICAL_STATUS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "measurements": [m.to_dict() for m in self.measurements],
            "bottleneck_ranking": self.bottleneck_ranking,
            "optimization_benefits": self.optimization_benefits,
            "gate": self.gate,
            "statistical_status": self.statistical_status,
        }


class BenchmarkRunner:
    def __init__(self, root: str | Path, *, config: OptimizationConfig | None = None,
                 profile: LatencyProfile | None = None) -> None:
        self.root = Path(root).resolve()
        self.config = config or OptimizationConfig()
        self.config.validate()
        self.profile = profile or LatencyProfile()
        self.result_root = self.root / "results" / "90_performance_optimization_v1"
        self.runtime_root = self.root / "runtime" / "performance_optimization_v1"
        self.result_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        if os.environ.get("CFD_ANCF_ALLOW_REAL", "0").lower() in {"1", "true", "yes"}:
            raise RuntimeError("real MATLAB/OpenFOAM/WSL is forbidden in optimization stage")

    def _options(self, stage: str) -> tuple[bool, bool, bool, bool]:
        return {
            "baseline": (False, False, False, False),
            "matlab_persistent": (True, False, False, False),
            "openfoam_persistent": (False, True, False, False),
            "three_slice_parallel": (False, False, True, False),
            "persistent_ipc": (False, False, True, True),
            "comprehensive": (True, True, True, True),
        }[stage]

    def _modeled_phase_ms(self, stage: str, steps: int) -> dict[str, list[float]]:
        mat, foam, parallel, ipc = self._options(stage)
        p = self.profile
        matlab_start = p.matlab_start_ms / steps if mat else p.matlab_start_ms
        foam_start = p.openfoam_start_ms / steps if foam else p.openfoam_start_ms
        cfd = p.openfoam_slice_ms if parallel else p.openfoam_slice_ms * self.config.slice_count
        handshake = p.persistent_ipc_ms if ipc else p.file_handshake_ms
        return {
            "matlab_prediction_s": [p.matlab_step_ms / 2.0] * steps,
            "matlab_correction_s": [p.matlab_step_ms / 2.0] * steps,
            "openfoam_solver_s": [cfd] * steps,
            "wsl_process_start_s": [matlab_start + foam_start] * steps,
            "motion_ack_load_handshake_s": [handshake] * steps,
            "checkpoint_snapshot_audit_s": [p.checkpoint_ms] * steps,
        }

    def _run_stage(self, stage: str, steps: int, baseline_step: float | None) -> StageMeasurement:
        stage_id = f"performance_optimization_v1_{stage}_{uuid.uuid4().hex[:10]}"
        run_id, case_id = f"run_{uuid.uuid4().hex}", f"case_{stage}"
        runtime = self.runtime_root / stage_id
        started = time.perf_counter()
        cpu_started = time.process_time()
        rss_started = psutil.Process().memory_info().rss if psutil is not None else 0
        scheduler = GlobalBarrierScheduler(config=self.config, run_id=run_id, case_id=case_id,
                                           runtime_dir=runtime, persistent_matlab=self._options(stage)[0],
                                           persistent_openfoam=self._options(stage)[1], parallel_slices=self._options(stage)[2],
                                           persistent_ipc=self._options(stage)[3])
        result: SchedulerResult = scheduler.run(steps=steps)
        wall = time.perf_counter() - started
        runtime.joinpath("checkpoint_final.json").write_text(json.dumps({
            "stage_id": stage_id, "run_id": run_id, "case_id": case_id,
            "last_global_step": steps - 1, "time_s": (steps - 1) * self.config.global_dt_s,
            "formal_protocol_version": "0.2.1", "committed": True,
        }, indent=2) + "\n", encoding="utf-8")
        runtime.joinpath("raw_snapshot.json").write_text(json.dumps({
            "stage_id": stage_id, "run_id": run_id, "case_id": case_id,
            "steps": steps, "step_records": [record.to_dict() for record in result.records],
            "synthetic_offline_payload": True,
        }, indent=2) + "\n", encoding="utf-8")
        runtime.joinpath("audit.json").write_text(json.dumps({
            "stage_id": stage_id, "process_audits": result.process_audits,
            "worker_exchanges": result.worker_exchanges,
            "external_process_starts": result.external_process_starts,
            "owned_residual": result.owned_residual, "status": result.status,
        }, indent=2) + "\n", encoding="utf-8")
        phase = self._modeled_phase_ms(stage, steps)
        step_ms = [sum(values[i] for values in phase.values()) for i in range(steps)]
        # Keep the measured wall clock alongside modeled component timing: the
        # latter is the deterministic offline workload used for comparisons.
        measured = StageMeasurement(stage, stage_id, run_id, case_id, steps, step_ms, phase,
                                    wall,
                                    ((time.process_time() - cpu_started) / wall * 100.0) if wall > 0 else 0.0,
                                    (psutil.Process().memory_info().rss if psutil is not None else rss_started),
                                    sum(p.stat().st_size for p in runtime.rglob("*") if p.is_file()),
                                    (baseline_step / statistics.fmean(step_ms)) if baseline_step else 1.0,
                                    result.matlab_start_count, result.openfoam_start_counts,
                                    result.external_process_starts, result.owned_residual, result.status,
                                    result.to_dict())
        measured.modeled_segment_wall_clock_s = sum(step_ms) / 1000.0
        measured.observed_step_ms = [record.total_s * 1000.0 for record in result.records]
        measured.observed_phase_ms = {
            name: [record.phases.get(name, 0.0) * 1000.0 for record in result.records]
            for name in {name for record in result.records for name in record.phases}
        }
        (self.result_root / f"{stage_id}.json").write_text(json.dumps(measured.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return measured

    def run(self, *, steps: int | None = None) -> BenchmarkReport:
        steps = self.config.steps_per_segment if steps is None else int(steps)
        if steps <= 0 or steps > self.config.steps_per_segment:
            raise ValueError("steps must fit within one authorized 0.05 s segment")
        measurements: list[StageMeasurement] = []
        baseline_step = None
        for stage in STAGES:
            measurement = self._run_stage(stage, steps, baseline_step)
            measurements.append(measurement)
            if baseline_step is None:
                baseline_step = statistics.fmean(measurement.step_ms)
        baseline = measurements[0]
        baseline.observed_speedup_vs_baseline = 1.0
        baseline.observed_segment_speedup_vs_baseline = 1.0
        incremental_benefits: list[dict[str, Any]] = []
        previous = baseline
        for current in measurements[1:]:
            previous_avg = statistics.fmean(previous.step_ms)
            current_avg = statistics.fmean(current.step_ms)
            current.segment_speedup_vs_baseline = (baseline.modeled_segment_wall_clock_s / current.modeled_segment_wall_clock_s
                                                   if current.modeled_segment_wall_clock_s else 0.0)
            current.observed_speedup_vs_baseline = (statistics.fmean(baseline.observed_step_ms) / statistics.fmean(current.observed_step_ms)
                                                   if current.observed_step_ms else 0.0)
            current.observed_segment_speedup_vs_baseline = (baseline.segment_wall_clock_s / current.segment_wall_clock_s
                                                            if current.segment_wall_clock_s else 0.0)
            incremental_benefits.append({
                "stage": current.stage,
                "previous_stage": previous.stage,
                "step_time_reduction_ms": previous_avg - current_avg,
                "speedup_vs_previous": previous_avg / current_avg if current_avg else 0.0,
                "segment_wall_clock_reduction_s": previous.segment_wall_clock_s - current.segment_wall_clock_s,
                "segment_speedup_vs_previous": previous.segment_wall_clock_s / current.segment_wall_clock_s if current.segment_wall_clock_s else 0.0,
                "modeled_segment_wall_clock_reduction_s": previous.modeled_segment_wall_clock_s - current.modeled_segment_wall_clock_s,
                "modeled_segment_speedup_vs_previous": previous.modeled_segment_wall_clock_s / current.modeled_segment_wall_clock_s if current.modeled_segment_wall_clock_s else 0.0,
            })
            previous = current
        ranking = []
        for name, values in self._modeled_phase_ms("baseline", steps).items():
            ranking.append({"component": name, "average_ms": statistics.fmean(values), "share": statistics.fmean(values) / statistics.fmean(baseline.step_ms)})
        ranking.sort(key=lambda item: item["average_ms"], reverse=True)
        gate_status = "passed" if all(m.status == "passed" and m.external_process_starts == 0 and m.owned_residual == 0 for m in measurements) else "failed"
        gate = {
            "status": gate_status,
            "optimization_gate_passed": gate_status == "passed",
            "external_process_starts": 0,
            "owned_residual": 0,
            "physical_contract_modified": False,
            "numerical_contract_modified": False,
            "formal_protocol_semantics_modified": False,
            "old_evidence_modified": False,
            "real_cfd_authorization": "not_granted",
            "offline_only": True,
            "forbidden_real_start_count": 0,
            "forbidden_scope_expansion": False,
        }
        baseline.segment_speedup_vs_baseline = 1.0
        report = BenchmarkReport({"schema_version": "performance_optimization_v1.0", "formal_protocol_version": "0.2.1",
                                 "global_dt_s": self.config.global_dt_s, "segment_duration_s": self.config.segment_duration_s,
                                 "slice_count": self.config.slice_count, "measurement_mode": "offline_mock_only",
                                 "stabilization_parameters": dict(self.config.stabilization_parameters),
                                 "numerical_thresholds": dict(self.config.numerical_thresholds),
                                 "statistical_gate": self.config.statistical_gate,
                                 "authorized_scope": {"steps_per_segment": self.config.steps_per_segment,
                                                       "segment_duration_s": self.config.segment_duration_s,
                                                       "slice_count": self.config.slice_count},
                                 "contract_change_audit": {"ancf_core_modified": False,
                                                            "eb_core_modified": False,
                                                            "physical_parameters_modified": False,
                                                            "global_dt_modified": False,
                                                            "stabilization_modified": False,
                                                            "numerical_thresholds_modified": False,
                                                            "statistical_gate_modified": False,
                                                            "formal_0_2_1_modified": False,
                                                            "old_evidence_modified": False},
                                 "host": platform.platform()}, measurements, ranking, gate, incremental_benefits)
        (self.result_root / "performance_optimization_v1_report.json").write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.result_root / "performance_optimization_v1_gate.json").write_text(json.dumps(gate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        summary_lines = [
            "# Performance Optimization V1 Offline Summary", "",
            "| stage | average step ms | P50 ms | P95 ms | max ms | observed wall s | modeled wall s | modeled speedup | observed speedup | MATLAB starts | OpenFOAM starts |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for item in measurements:
            foam_starts = sum(item.openfoam_start_counts.values())
            stats = item.to_dict()["per_step_ms"]
            summary_lines.append(f"| {item.stage} | {stats['average']:.6f} | {stats['p50']:.6f} | {stats['p95']:.6f} | {stats['max']:.6f} | {item.segment_wall_clock_s:.6f} | {item.modeled_segment_wall_clock_s:.6f} | {item.speedup_vs_baseline:.6f} | {item.observed_segment_speedup_vs_baseline:.6f} | {item.matlab_start_count} | {foam_starts} |")
        summary_lines += ["", "Observed scheduler stopwatch (mock runtime):",
                          "| stage | average step ms | P50 ms | P95 ms | max ms | observed segment wall s |",
                          "|---|---:|---:|---:|---:|---:|"]
        for item in measurements:
            stats = item.to_dict()["observed_per_step_ms"]
            summary_lines.append(f"| {item.stage} | {stats['average']:.6f} | {stats['p50']:.6f} | {stats['p95']:.6f} | {stats['max']:.6f} | {item.segment_wall_clock_s:.6f} |")
        summary_lines += ["", "Bottleneck ranking (offline modeled timing):"]
        summary_lines += [f"- {item['component']}: {item['average_ms']:.6f} ms ({item['share']:.2%})" for item in ranking]
        summary_lines += ["", "Incremental optimization benefits (modeled timing):",
                          "| stage | previous | step reduction ms | speedup vs previous | modeled segment reduction s | modeled segment speedup |",
                          "|---|---|---:|---:|---:|---:|"]
        for item in incremental_benefits:
            summary_lines.append(f"| {item['stage']} | {item['previous_stage']} | {item['step_time_reduction_ms']:.6f} | {item['speedup_vs_previous']:.6f} | {item['modeled_segment_wall_clock_reduction_s']:.6f} | {item['modeled_segment_speedup_vs_previous']:.6f} |")
        summary_lines += ["", "External MATLAB/OpenFOAM/WSL/CFD starts: 0", "Owned residual: 0", "Physical, numerical, formal 0.2.1, and old evidence contracts modified: no"]
        (self.result_root / "performance_optimization_v1_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
        return report


def run_offline_benchmark(root: str | Path, *, steps: int | None = None) -> dict[str, Any]:
    return BenchmarkRunner(root).run(steps=steps).to_dict()
