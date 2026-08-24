# C++ worker persistent IPC bounded confirm

- Gate: `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: pass`
- segment wall-clock: 21.0860833 s
- physical committed: 40
- fully audited: 40
- C++ worker startup: 1
- OpenFOAM startup: 3
- WSL startup: 3
- MATLAB startup: 0 (forbidden by this path)
- owned residual: 0
- T_ancf mean: 0.004191145000000063 s
- T_openfoam mean: 0.3103975149999999 s
- T_exchange mean: 0.5314718450000006 s
- T_sync_and_audit mean: 0.005777362500000227 s
- T_ancf P50/P95: 0.003987750000000734 / 0.004794050000000194 s
- T_openfoam P50/P95: 0.3114930999999981 / 0.3716234349999995 s
- T_exchange P50/P95: 0.26096880000000056 / 0.3100825650000023 s
- T_sync_and_audit P50/P95: 0.005519600000000402 / 0.007080555000001087 s
- speedup versus 35.4478716 s baseline: 1.6811027015149846x
- speedup versus 37.1570657 s baseline: 1.7621606237323362x
- dominant measured phase: `T_exchange_s`
- load contract repair: current correction used committed applied load; current raw load was committed as next-step applied load
- C++ numerical core status: `not_completed` (transport/worker path only)

The source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.
