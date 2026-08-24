# Performance Optimization V1 Acceptance Matrix

This matrix is evidence for the offline-only optimization gate. It does not
authorize a real MATLAB, OpenFOAM, WSL, or CFD run.

| Requirement | Evidence | Current result |
|---|---|---|
| Baseline and five optimization stages | `results/90_performance_optimization_v1/performance_optimization_v1_report.json` and `performance_optimization_v1_summary.md` | 6 stages, 20 authorized steps each |
| Per-step timing statistics | Report `per_step_ms`, `observed_per_step_ms`, `phase_ms`, `observed_phase_ms` | average, P50, P95, maximum present |
| MATLAB persistent lifecycle | Report `matlab_start_count`, `worker_exchanges.matlab`, process audit | comprehensive: 1 start, 20 requests, 20 responses |
| OpenFOAM persistent lifecycle | Report `openfoam_start_counts`, slice exchanges, process audit | comprehensive: 3 starts, 20 exchanges per slice |
| Three-slice parallel barrier | `tests/performance_optimization_v1/test_workers_scheduler.py` | overlap test and checkpoint wait test pass |
| Persistent IPC fail-closed rules | `tests/performance_optimization_v1/test_ipc.py` | stale, duplicate, out-of-order, timeout, disconnect, identity, hash, ack and bridge-step faults pass |
| Worker failure fail-closed rules | `test_missing_output_and_identity_faults_fail_closed` | missing output, NaN, 5001, identity/tick/time faults pass |
| Checkpoint/raw snapshot evidence | newest comprehensive runtime under `runtime/performance_optimization_v1/` | 20 checkpoint and 20 raw snapshot audit files |
| No external engine starts | report Gate and runtime audit | MATLAB/OpenFOAM/WSL/CFD starts = 0 |
| No owned residual | report Gate and runtime audit | residual = 0 |
| Contract preservation | report `config.contract_change_audit`, Gate | ANCF/EB, physical, numerical, dt, stabilization, thresholds, statistics, formal 0.2.1 and old evidence unchanged |
| Statistical status | report `statistical_status` | frequency not evaluable; Strouhal, stable VIV and lock-in not completed |
| Regression/build | command evidence | `compileall src tests tools` passes; root unittest 951 tests, 1 skipped, OK |

The deterministic modeled timing is used for cross-stage speedup because the
offline mock is intentionally too fast for observed wall-clock timing to be a
stable performance proxy. Observed stopwatch timings remain in the report for
audit and reproducibility.
