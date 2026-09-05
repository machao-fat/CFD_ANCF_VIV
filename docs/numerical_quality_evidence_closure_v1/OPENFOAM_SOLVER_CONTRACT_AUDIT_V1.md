# OpenFOAM solver-contract audit V1

## Scope and immutability

This is a read-only audit of `stage_force_contract_smoke_v1_run_008`. Its raw
stdout is retained at `runtime/stage_force_contract_smoke_v1_run_008/logs/` and
the structured result records its SHA-256. The audit neither changes the
run_008 contract nor reclassifies its frozen V1 result: V1 remains **FAIL**.

## Actual `fvSolution`

The audited slice-0000 case uses `nOuterCorrectors=1`, `nCorrectors=2`, and
`nNonOrthogonalCorrectors=0`; its runtime header independently says it is
operating with one outer corrector in PISO mode. No `residualControl` block is
present.

| Field/configuration | Solver | Absolute tolerance | relTol |
| --- | --- | ---: | ---: |
| `p` | GAMG / DIC | 1e-8 | 0.01 |
| `pFinal` | inherits `p` | 1e-8 | 0 |
| `pcorr` | GAMG / GaussSeidel | 1e-2 | 0 |
| `pcorrFinal` | inherits `pcorr` | 1e-2 | 0 |
| `U` | PBiCGStab / DILU | 1e-8 | 0.1 |
| `UFinal` | inherits `U` | 1e-8 | 0 |
| `cellMotionUx` | PCG / DIC | 1e-8 | 0 |

## The two V1 violations

| Time (s) | Field | Solve index | Final residual | Outer corrector | Pressure corrector | Non-orthogonal corrector | Terminal for field? | Terminal `p` residual |
| ---: | --- | ---: | ---: | --- | --- | --- | --- | ---: |
| 0.005 | `p` | 3 | 0.00445800788829 | 1 | unknown | 0 | no | 9.41975628408e-9 |
| 0.015 | `p` | 3 | 0.00462973685818 | 1 | unknown | 0 | no | 7.04122362515e-9 |

The raw log does not label pressure-corrector indices. V1 therefore records
them as `unknown`, not an inferred value. The outer index is known to be one
because the actual configuration permits only one outer corrector. The two
rows are intermediate in the observable sense that a later `p` solve occurs in
the same time record; the last parsed `p` solve is the terminal per-field row.

Across all 200 times, the largest terminal residuals are `Ux=9.99659849617e-9`,
`Uy=8.48413096951e-9`, and `p=9.983874437e-9`. Maximum Courant number is
0.350855773225 and the largest absolute parsed global continuity value is
1.10665568732e-8. There is no raw-log evidence of numerical divergence.

## Answer on the frozen V1 gate

The answer is **NO**: its universal `1e-3` bound on the maximum final residual
over *every* `Solving for` line has no direct solver-contract basis. It mixes
the first `p` solve, whose configured relative tolerance is 0.01, with the
terminal `pFinal` solve, whose `relTol` is zero and absolute tolerance is 1e-8.
The V1 measurement is still valuable as an intermediate-iteration diagnostic,
but it cannot by itself represent terminal PIMPLE/PISO convergence.

There is no numerical basis for a retrospective startup exemption. The
terminal values meet the terminal tolerances from the first step; V1 is kept
failed because its already-frozen metric has its specified two violations.
