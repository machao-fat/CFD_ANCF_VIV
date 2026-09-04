# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: pass`
- segment wall-clock: 22.727814900000002 s
- physical committed: 40
- fully audited: 40
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.022216654999999957 s
- T_openfoam mean: 0.3102624000000004 s
- T_exchange mean: 0.1922183700000002 s
- T_sync_and_audit mean: 0.019750482500000242 s
- C++ numerical core status: `validated` under the protected MATLAB/C++ engineering-tolerance dual-run contract; this confirm does not change that contract.

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started. This was the separately authorized stage196 bounded confirm using a fresh run/runtime/case identity.
