# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass`
- segment wall-clock: 14.3441546 s
- physical committed: 19
- fully audited: 19
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.0029631842105265014 s
- T_openfoam mean: 0.3311273263157893 s
- T_exchange mean: 0.8501757684210522 s
- T_sync_and_audit mean: 0.005208405263158127 s
- C++ numerical core status: `not_completed` (transport/worker path only)

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
