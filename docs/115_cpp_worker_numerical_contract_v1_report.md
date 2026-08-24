# MATLAB/C++ Numerical Contract V1

The independent 40-step dual run passed the explicit cross-solver numerical contract. The original bitwise-style comparison remains recorded as 0/40; this is expected for independent MATLAB BLAS/LAPACK and C++ linear algebra paths and is not used as a physical equivalence requirement.

Contract results: q max absolute error `4.1084e-5` against `1e-4`; qdot `1.7808e-3` against `5e-3`; qddot `0.5118` against `1.0`; internal force `397.1143` against `500`; predictor/corrector `4.1084e-5` against `1e-4`; residual `0.01006` against `0.02`. External/generalized force differences were below `4e-12`. All 40 steps were processed with one resident C++ worker and owned residual zero.

This audit does not alter physical parameters, global dt, Newton thresholds, statistical gates, or protocol semantics. It authorizes only the next offline/mock integration step. Real OpenFOAM, WSL, and CFD remain separately unauthorized.

`STAGE4F_D_CPP_WORKER_MATLAB_CPP_NUMERICAL_CONTRACT_V1_GATE: pass`
