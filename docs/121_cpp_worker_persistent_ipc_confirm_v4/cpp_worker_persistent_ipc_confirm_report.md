# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass`
- segment wall-clock: 15.786574199999999 s
- physical committed: 23
- fully audited: 23
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.002969213043477979 s
- T_openfoam mean: 0.3203759652173912 s
- T_exchange mean: 0.8193679173913049 s
- T_sync_and_audit mean: 0.00552051739130431 s
- C++ numerical core status: `not_completed` (transport/worker path only)

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
