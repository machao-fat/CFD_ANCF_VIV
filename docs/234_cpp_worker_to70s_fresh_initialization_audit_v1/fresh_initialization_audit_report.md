# Fresh step-0 initialization audit

- Gate: `STAGE4F_D_CPP_WORKER_TO70S_FRESH_INITIALIZATION_AUDIT_V1_GATE: do_not_pass`
- No real MATLAB/OpenFOAM/WSL/CFD process was started.
- The accepted step 559 checkpoint is `2.2075 s`, not physical `t=0`.
- The target 50 m, `dt=0.00125` template lacks `U/Uf/meshPhi/p/phi` at both `0` and `2.2075`.
- The only complete step-0 candidate has a different 10 m/`dt=0.0025` contract and is rejected.

A fresh run requires a matched t=0 CFD field set and matching ANCF `q/qdot/qddot`; no continuation is authorized until those artifacts are produced and audited.
