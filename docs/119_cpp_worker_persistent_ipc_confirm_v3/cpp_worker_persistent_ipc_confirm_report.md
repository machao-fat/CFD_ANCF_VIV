# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass`
- segment wall-clock: 14.895322199999999 s
- physical committed: 23
- fully audited: 23
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.003420117391304139 s
- T_openfoam mean: 0.30674829565217393 s
- T_exchange mean: 0.7730640000000003 s
- T_sync_and_audit mean: 0.005263191304347753 s
- C++ numerical core status: `not_completed` (transport/worker path only)

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
