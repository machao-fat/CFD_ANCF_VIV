# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_TO30S_V1_RETRY1_GATE: do_not_pass`
- segment wall-clock: 1657.0042635999998 s
- physical committed: 3200
- fully audited: 3200
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.02491895887500179 s
- T_openfoam mean: 0.3643473487812499 s
- T_exchange mean: 0.10484952737499938 s
- T_sync_and_audit mean: 0.04126677612499975 s
- C++ numerical core status: `validated`

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
