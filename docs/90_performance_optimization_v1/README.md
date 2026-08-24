# CFD_ANCF_VIV Performance Optimization V1

This stage is an offline performance study only. It does not start MATLAB,
OpenFOAM, WSL, or CFD and it does not reuse historical partial runtimes.

The benchmark uses independent `stage_id`, `run_id`, `case_id`, runtime, and
result paths for six measurements: baseline, MATLAB persistent, OpenFOAM
persistent, three-slice parallel, persistent IPC, and the comprehensive mode.
Each step records MATLAB prediction/correction, OpenFOAM work, process-start,
motion/ack/load handshake, checkpoint/snapshot audit, and total timing. The
report includes average, P50, P95, maximum, segment wall clock, speedup,
CPU/memory/disk fields, process lifecycle records, and owned residual. Since
the mock engine is intentionally fast, `segment_wall_clock_s` is the observed
Python wall clock and `modeled_segment_wall_clock_s` is the deterministic
offline component sum used for cross-stage speedup comparisons.

The mock workers enforce the requested fail-closed behavior for non-zero/5001
returns, timeout, disconnect, stale or duplicate IPC messages, out-of-order
sequence, identity/tick/time mismatch, and non-finite output. The scheduler
does not submit the next step or commit a checkpoint until all three slices
have completed the current global barrier.

Run from this directory with:

```text
python tools/performance_optimization_v1/run_benchmark.py --steps 20
```

The generated gate explicitly states that physical parameters, numerical
contracts, formal 0.2.1 semantics, and old evidence are unchanged. It does
not grant authorization for a real CFD segment; a new explicit authorization
is required after review.

See `acceptance_matrix.md` for requirement-to-evidence mapping and the exact
offline verification scope.
