# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: pass`
- segment wall-clock: 22.701170599999998 s
- physical committed: 40
- fully audited: 40
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.020431807500000045 s
- T_openfoam mean: 0.3083936524999999 s
- T_exchange mean: 0.19350066000000016 s
- T_sync_and_audit mean: 0.01914842499999987 s
- C++ numerical core status: `not_completed` (transport/worker path only)

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
