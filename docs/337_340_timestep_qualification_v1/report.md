# 时间步资格化与敏感性测试

## Completed windows

| Stage | dt (s) | physical window | steps | wall clock | Gate |
|---|---:|---:|---:|---:|---|
| 337 baseline | 0.0025 | 1.0 s | 400 | 871.39 s | pass |
| 338 comparison | 0.005 | 5.0 s | 1000 | 2211.25 s | pass |
| 339 comparison | 0.0025 | 5.0 s | 2000 | 4007.81 s | pass |
| 340 fine sensitivity | 0.00125 | 0.1 s | 80 | 166.38 s | pass |

All windows used fresh runtimes, three slices, `inverseDistance 1(cyl)`, the C++ worker, and preCICE. MATLAB starts were zero. OpenFOAM and C++ return codes were zero, fluid stderr was empty, slices were synchronized, and owned residual was zero.

## Comparison interpretation

The final structural-state L2 relative difference between the 5 s `dt=0.005` and `dt=0.0025` windows was `3.21e-6`. Instantaneous end-of-window force components differ more because the two runs are sampled at different temporal grids and remain in a transient regime. Windowed lift RMS differences were approximately 22% in the middle window and 28% in the final window; the early window differed more because it contains the startup transient. Formal frequency/amplitude convergence is not evaluable: there are fewer than 15 cycles and the existing observability summary lacks full Courant/continuity aggregates.

The `dt=0.00125 s` short test now completes 80/80 steps without the Stage335 `sigFpe`; it is only a numerical smoke, not a fine-grid reference solution.

## Decision

`dt=0.005 s` is operationally stable but is **not yet promoted** to the formal production timestep. A long run may be requested only after explicit authorization, with convergence statistics retained. The current production candidate remains `dt=0.0025 s` until a post-transient same-window comparison satisfies the existing thresholds.

Formal status remains `FORMAL_STROUHAL_STATUS=not_completed`, `STABLE_VIV_RESPONSE_CLAIM=not_completed`, and `LOCK_IN_CLAIM=not_completed`.
