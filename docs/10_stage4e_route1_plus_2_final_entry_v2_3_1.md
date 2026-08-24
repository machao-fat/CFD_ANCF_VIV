# Stage 4E Route 1+2 v2.3.1 final entry decision

## Decision

The authorization defect has been corrected and scenario S has been run once
on the medium mesh using real OpenFOAM 10 kOmegaSSTLM. The run is numerically
healthy and reproducible, but both N and S fail the frozen low-amplitude
frequency evaluability gate. No frequency, St, or high-Re physical conclusion
is promoted.

## Entry boundary

The following remain explicitly outside this task:

- fine-mesh computation;
- a third turbulence or transition input;
- low or middle Reynolds cases;
- nine-slice CFD;
- ANCF coupling or free VIV;
- lock-in or experimental amplitude validation.

The methodology mainline continuation is pending Sol review. A low-Re
multi-slice method entry is not authorized by this closeout. Entry to a real
high-Re nine-slice case is not recommended.

## Evidence anchors

- scenario S: 14,001 production force samples from 2 to 9 s;
- maximum production CFL: 0.1366819923969757;
- maximum cylinder yPlus p95: 0.3953372410487625;
- force cross-check: passed at the 1e-10 criterion;
- scenario S frequency status: `not_evaluable_low_amplitude`;
- effective cycles: 0;
- root regression: 591 tests passed;
- v2.3.1 specialized regression: 19 tests passed;
- task-owned residual processes: 0.

The formal Stage 4E gate remains not passed by this task. The result is a
restricted engineering pilot closeout, not a declaration of real nine-slice
CFD readiness.
