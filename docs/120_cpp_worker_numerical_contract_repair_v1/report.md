# C++ ANCF numerical-contract repair

- Gate: `STAGE4F_D_CPP_WORKER_NUMERICAL_CONTRACT_REPAIR_V1_GATE: pass`
- Root cause: historical fixture used gauss order 5 / Newton limit 50; the ANCF contract is order 3 / limit 40.
- Offline replay: 40/40 finite steps.
- C++ worker startup: 1
- MATLAB/OpenFOAM/WSL/CFD starts: 0
- owned residual: 0
- Real confirm 003 remains fail-closed at step 583 and was not retried.

No physical parameters, global dt, thresholds, formal protocol semantics, old evidence, or old runtime were modified. A new explicit real-confirm authorization is still required.
