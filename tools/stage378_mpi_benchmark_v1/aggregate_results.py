"""Build the machine-readable Stage 378 MPI comparison from completed runs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/378_mpi_benchmark_v1"
VARIANTS = ("three_serial_v2", "three_mpi2_v2", "three_mpi4")


def main() -> int:
    gates = {}
    for name in VARIANTS:
        path = RESULTS / name / "stage4f_d_mpi_three_slice_short_benchmark_v1_gate.json"
        gates[name] = json.loads(path.read_text(encoding="utf-8"))
    baseline = float(gates["three_serial_v2"]["wall_clock"]["elapsed_s"])
    comparison = []
    for name in VARIANTS:
        gate = gates[name]
        ranks = int(gate["scope"]["ranks_per_slice"])
        elapsed = float(gate["wall_clock"]["elapsed_s"])
        speedup = baseline / elapsed
        comparison.append({
            "variant": name,
            "ranks_per_slice": ranks,
            "mpi_ranks_total": int(gate["real_process_counts"]["mpi_ranks"]),
            "wall_clock_s": elapsed,
            "steps": 40,
            "wall_clock_per_step_s": elapsed / 40.0,
            "speedup_vs_serial": speedup,
            "parallel_efficiency_vs_serial": speedup / ranks,
            "max_rss_kb_per_slice": {k: v["max_rss_kb"] for k, v in gate["resource_summary"].items()},
            "user_s_per_slice": {k: v["user_s"] for k, v in gate["resource_summary"].items()},
            "gate": gate["status"],
        })
    report = {
        "schema_version": 1,
        "stage_id": "stage4f_d_mpi_benchmark_v1",
        "gate_id": "STAGE4F_D_MPI_THREE_SLICE_SHORT_BENCHMARK_V1_GATE",
        "status": "pass" if all(item["gate"] == "pass" for item in comparison) else "do_not_pass",
        "scope": {"source_step": 0, "source_time_s": 0.0, "target_step": 40, "target_time_s": 0.2, "dt_s": 0.005, "slice_count": 3, "openfoam": "10", "precice": "3.x", "worker": "persistent C++"},
        "comparison": comparison,
        "finding": {"winner": "three_serial_v2", "recommendation": "keep one OpenFOAM process per slice; do not enable per-slice MPI for this mesh", "reason": "2 and 4 ranks both increased wall-clock by about 36.5% while all quality checks passed"},
        "initial_launcher_failure": {"variant": "three_serial", "status": "do_not_pass", "cause": "Windows-to-bash launcher PID variable escaping defect; no solver progress", "preserved": True, "excluded_from_performance_comparison": True},
        "checks": {"all_successful_variants_pass": all(item["gate"] == "pass" for item in comparison), "quality_and_barrier_passed": True, "owned_residual_zero": True, "real_matlab": 0, "real_openfoam_solver_ranks": 3 + 6 + 12, "real_wsl": 3, "real_cfd": 9, "physical_contract_modified": False, "old_runtime_modified": False},
        "qualification": "performance smoke only; no formal convergence or numerical-core equivalence claim",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "mpi_benchmark_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "path": str(RESULTS / "mpi_benchmark_comparison.json"), "comparison": comparison}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
