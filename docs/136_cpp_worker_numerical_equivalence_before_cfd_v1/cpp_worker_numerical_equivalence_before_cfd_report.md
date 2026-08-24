# C++ ANCF numerical equivalence before CFD

- Gate: `STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: do_not_pass`
- MATLAB native contract: Gauss 5, max_newton 50
- Existing C++ confirm contract: Gauss 3, max_newton 40
- Contract mismatch: `mismatch`
- Protected step559 single-step: candidate only; no MATLAB prediction/correction golden exists in the immutable seed MAT.
- Available 40-step MATLAB golden replay: strict 0/40, engineering 40/40, but source identity match is false (golden source step 603).
- Fault injection: `pass`; all required cases fail-closed.
- Real starts: MATLAB=0, OpenFOAM=0, WSL=0, CFD=0; C++ worker starts=2; owned residual=0.

The numerical Gate remains fail-closed because the accepted step559 MATLAB correction/prediction golden is missing and the native MATLAB contract differs from the existing C++ confirm contract. No physical parameters, thresholds, old evidence, or old runtime were modified. CFD remains forbidden until a matching MATLAB export and a new offline Gate are available.
