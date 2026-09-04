# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_LONG_WINDOW_V1_RETRY2_GATE: pass`
- segment wall-clock: 409.1786765 s
- physical committed: 800
- fully audited: 800
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.025639549750000257 s
- T_openfoam mean: 0.3696187531250005 s
- T_exchange mean: 0.10494664724999986 s
- T_sync_and_audit mean: 0.028193693999999124 s
- C++ numerical core status: `validated`

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
