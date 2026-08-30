# Stage336: dt=0.005 s, 1 s qualification

## Scope

- fresh zero state, three slices;
- `inverseDistance 1(cyl)` moving mesh;
- `dt=0.005 s`, 200 steps, target time 1.0 s;
- compact output (`purgeWrite=1`) with per-step mapping/barrier audit and checkpoints;
- no MATLAB; C++ worker and three OpenFOAM participants only.

## Result

Gate: `STAGE4F_D_DT005_ONE_SECOND_QUALIFICATION_V1_GATE: pass`

Wall clock was `432.66 s` (`7 min 13 s`). All three slices reached time 1.0 s and all 200 structure barriers/mapping records were committed. Structure and fluid return codes were zero, fluid stderr was empty, final moving-mesh fields were present and nonzero, and `owned_residual=0`.

The real process counts were MATLAB=0, OpenFOAM=3, WSL=1, CFD=3, C++ worker=1, and preCICE structure=1. This is a one-second qualification/smoke result, not formal timestep independence, VIV convergence, or a license to start a longer run. `FORMAL_STROUHAL_STATUS`, `STABLE_VIV_RESPONSE_CLAIM`, and `LOCK_IN_CLAIM` remain `not_completed`.

Stage335's `dt=0.00125 s` failure remains isolated and unchanged. No ANCF/EB core, physical parameter, global study scope, threshold, or formal protocol was modified.
