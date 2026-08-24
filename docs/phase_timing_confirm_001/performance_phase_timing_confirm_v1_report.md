# 性能分段计时确认

- stage_id: `stage4f_d_performance_phase_timing_confirm_v1`
- run_id: `performance_phase_timing_confirm_001`
- scope: 40 steps, 3 slices, 0.05 s
- segment wall-clock: 37.157066 s
- step wall-clock sum: 31.149152 s
- main measured interval: `T_ancf`; effective CFD barrier remains the largest solver-side wall component
- physical committed / fully audited: 40 / 40
- MATLAB/OpenFOAM/WSL starts: 1 / 3 / 3
- owned residual: 0

| phase | mean (s) | P50 (s) | P95 (s) | max (s) | mean/T_step | interval weight |
|---|---:|---:|---:|---:|---:|---:|
| T_ancf | 0.490764640 | 0.489013400 | 0.544208300 | 0.573871900 | 63.021% | 32.385% |
| T_openfoam | 0.341260965 | 0.354307900 | 0.400974800 | 0.404544500 | 43.823% | 22.519% |
| T_exchange | 0.396076997 | 0.397497400 | 0.457417800 | 0.467900200 | 50.862% | 26.137% |
| T_sync_and_audit | 0.287310097 | 0.290672400 | 0.308463700 | 0.335728200 | 36.895% | 18.959% |

Slice mean ranking: slice_2=0.336068925s, slice_1=0.335187690s, slice_0=0.334320785s. Mean global-barrier wait: 0.011393335 s; max: 0.077236100 s. Total overlap_gap: 29.467356100 s, so phase weights are descriptive and not additive.

Root cause of elapsed time: the timing confirm measures the existing persistent-worker, parallel three-slice path; no new physics or threshold was introduced. The largest measured interval is ANCF's predict-to-correct envelope, while OpenFOAM slice barrier is the actionable solver-side bottleneck and slice imbalance is small.

No old evidence, physical parameters, numerical thresholds, or formal protocol semantics were modified. Stage75/E5-B/E5-C and all broader studies were not started.

Gate: `STAGE4F_D_PERFORMANCE_PHASE_TIMING_CONFIRM_V1_GATE: pass`
