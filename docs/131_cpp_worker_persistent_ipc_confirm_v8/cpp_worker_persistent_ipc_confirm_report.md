# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass`
- segment wall-clock: 13.3688951 s
- physical committed: 19
- fully audited: 19
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.002910684210526596 s
- T_openfoam mean: 0.30279365789473683 s
- T_exchange mean: 0.8300516105263164 s
- T_sync_and_audit mean: 0.005217478947368436 s
- C++ numerical core status: `not_completed` (transport/worker path only)

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
