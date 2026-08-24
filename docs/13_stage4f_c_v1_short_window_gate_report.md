# Stage 4F-C-v1 three-slice short-window Gate report

## Gate

Stage 4F-C-v1 is blocked at the allowed failure terminal
`failure_environment_blocked_before_branch_A_step0`. The short-window
numerical status is not accepted.

The accepted parent checkpoint was materialized into an isolated branch-A
case, but the first ANCF prediction failed before any OpenFOAM process was
started. MATLAB R2021b returned MathWorks ApplicationService communication
error 5001. A separate `-wait/-logfile` version/license probe reproduced the
same error, and the unfiltered root test suite reproduced it through the
independent persistent-ANCF entry point.

## Completed work

- The A/B/C time grids, norms, absolute scales, impulse quadrature and hard
  gates were frozen before real execution. Contract SHA-256:
  `f8d6224093c41f0050e36b844b187263805550eb0488eec1e92962e0b4ff34ef`.
- The 32-file parent protection set was unchanged before and after the
  attempt. Combined SHA-256:
  `9e51091ce3b62dc379769db6ff8ea0a7afe47950bb60b92615b2990ea9e2ee01`.
- `compileall` passed. The v1 targeted suite passed 26/26 tests, including
  contract mutation, strict CFL, force scaling, FATAL/non-finite, geometry
  and near-zero denominator tests.
- The post-fix unfiltered root suite ran all 671 tests: 667 passed, zero
  assertion failures occurred, and the four real persistent-ANCF tests had
  the same MATLAB environment error during setup.
- The branch-A attempt and independent probe registered 2/2 closed launcher
  records. The four root-regression MATLAB sessions registered 32/32 closed
  PID/creation-time records. Total registered records were 34/34 closed with
  zero residual. No OpenFOAM process was started.

## Implementation hardening

The failed environment run exposed no numerical result, but the independent
code review found two pre-execution audit weaknesses. They were corrected
without changing the frozen JSON or any threshold: contract validation now
rejects branch-dt, runtime-identity and parent-identity mutations even if an
attacker recomputes the internal contract hash; force conversion near zero
now uses the frozen `500 N/m` raw-to-unit scale and `25000 N` integrated-force
scale. The existing frozen contract validates unchanged, and a second Terra
read-only review found no blocking issue.

## Failure location and repair

The first failed phase is branch A, global step 0, ANCF prediction. There is
no failed slice because CFD was never launched. No checkpoint was committed,
and B/C were correctly not authorized.

ServiceHost logs expose an existing Connector PID 41904, but it was not
created by this task and process inventory access is denied. It was retained
and not terminated. The minimum repair is to close or restart the existing
MathWorks Connector/ServiceHost through its owning user session (or perform a
user logoff/reboot), then require one successful R2021b version/license probe.
Only after that may a fresh attempt2 restart branch A under the unchanged
contract. No threshold, geometry, domain, protocol or ANCF-core change is
authorized.

## Scope boundary

No 0.05 s CFD window was completed. This result is not vortex-shedding
statistics, stable VIV response, lock-in evidence, experimental validation,
or Stage 4E physical validation. Five slices, nine slices, long-time VIV and
extended transient work remain prohibited.
