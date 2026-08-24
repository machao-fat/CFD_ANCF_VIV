# Stage 4F-B-A: selected low-Re structure transient numerical qualification

## Status and scope

Status: **passed within synthetic-load diagnostic scope only**.  This evidence uses the existing nonlinear ANCF core in MATLAB R2021b and does not run OpenFOAM.  It is not an FSI calculation, a VIV prediction, a lock-in result, or experimental validation.

The frozen Stage 4F-A-v2.1 selection was used without changing its protocol or structural core: `D=1 m`, `L=50 m`, `Re=100`, `U=1 m/s`, `m*=5`, `beta=0.01`, `T=2179104.0029808935 N`, `E=3227125779.2218256 Pa`, `EA=481569945.41014224 N`, and `EI=54477600.07452233 N m^2`.  ANCF `nElem=16` is the production mesh used here; `nElem=32` remains the declared reference mesh and was not re-run for this narrowly scoped transient diagnostic.

## Controlled load and run matrix

Three centerline slices are placed at the existing equal-span ANCF locations.  The imposed load is an explicitly synthetic, spatially first-order sinusoidal transverse line load:

`f_2D(t) = 0.5 rho U^2 D Cy sin(2 pi f t)` in N/m,

with `rho=1000 kg/m^3`, `Cy=0.30`, and `f=0.18181818181818182 Hz`.  Each integrated slice force is applied in global y as `F_i=f_2D*(L/3)`, where `L/3=16.666666666666668 m`; this length multiplication occurs once only, before the core's integrated-force mapping.  The simulated interval is `0.025 s`.

| Case | dt (s) | Steps | Checkpoint |
|---|---:|---:|---|
| Production coarse | 0.0025 | 10 | none |
| Production fine | 0.00125 | 20 | none |
| Restart | 0.0025 | 5 + reload + 5 | ANCF full-state MAT checkpoint |

## Results

| Metric | Coarse | Fine | Restart |
|---|---:|---:|---:|
| All finite / Newton converged | yes / yes | yes / yes | yes / yes |
| Maximum Newton iterations | 2 | 2 | 2 |
| Minimum tension (N) | 638152.807163 | 638152.807164 | 638152.807163 |
| Maximum abs. Green strain | 0.004504752704 | 0.004504752704 | 0.004504752704 |
| Mechanical energy change (J) | 7.2672963e-5 | 7.9691410e-5 | 7.2672963e-5 |
| Synthetic external work (J) | 7.7970207e-5 | 8.2537500e-5 | 7.7970207e-5 |
| Damping dissipation (J) | 0 | 0 | 0 |
| Energy residual (J) | -5.2972441e-6 | -2.8460900e-6 | -5.2972441e-6 |
| Relative energy residual | 5.2972441e-6 | 2.8460900e-6 | 5.2972441e-6 |

The normalized final-state difference between `dt=0.0025 s` and `dt=0.00125 s` is `6.4438655e-10`.  The restart versus uninterrupted coarse run has relative full-state error `0`, satisfying the `1e-11` limit.

## Stop-condition audit

No stop condition was triggered: NaN/Inf absent; every Newton solve converged; no significant negative tension; Green strain remained below 1%; restart error was below `1e-11`; and relative energy residual was below `1e-3`.  The damping matrix supplied by this frozen construction is zero, so the zero dissipation is an audited model setting, not a claim that physical fluid or structural damping was identified.

## Evidence and limits

The machine-readable result is `results/12_stage4f_transient_certification/stage4f_b_a_transient_certification.json`; the restart artifact is in `runtime/stage4f_transient_certification/ancf_n16_step5_checkpoint.mat`.  The runner is `src/structure_ancf_matlab/stage4f_transient_certification/run_stage4f_transient_certification.m`.

This qualifies short-duration solver behavior under a prescribed synthetic force only.  It provides no fluid-force validation, wake response, added damping identification, VIV amplitude/frequency, lock-in, long-time statistics, or experimental comparison.  A future real three-slice low-Re FSI preflight must preserve these scope limits and independently qualify the coupling and fluid solve.
