# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass`
- segment wall-clock: 14.7665486 s
- physical committed: 22
- fully audited: 22
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.0046867999999997585 s
- T_openfoam mean: 0.30065093636363655 s
- T_exchange mean: 0.7602191045454544 s
- T_sync_and_audit mean: 0.005382322727272419 s
- C++ numerical core status: `not_completed` (transport/worker path only)

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
