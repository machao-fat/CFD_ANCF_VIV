# GENERALIZED_FORCE_METRIC_V2_AND_0P1S_MICRO_SMOKE_V1

## Decision

`CORRECTED_MOVING_MESH_0P1S_SMOKE = FAIL`.

The fresh run `generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001` was
started from t=0 with the frozen 0.005 s step and stopped after 13 committed
windows (t=0.065 s).  It did pass the old t=0.05 s generalized-force failure
point.  At the attempted step 14 (t=0.070 s), all fluid participants suffered
a floating-point exception; the structure participant then observed the C++
worker disconnect.  No retry was performed.

## V2 mapping result

The pre-run V2 contract is PASS.  Position DOFs are m/N conjugate pairs;
slope DOFs are dimensionless/N m pairs.  Its per-DOF, contribution-scaled
formula, floors, and ULP rationale are in
[`GENERALIZED_FORCE_METRIC_V2_CONTRACT.md`](GENERALIZED_FORCE_METRIC_V2_CONTRACT.md).

All 13 returned correction attempts passed V2.  Their maximum V2 threshold
utilization was `0.036194961276627934`; maximum contribution-normalized error
was below the frozen tolerance.  The largest legacy absolute difference was
`5.960464477539063e-08`, a deliberately diagnostic mixed-unit number.  The
immutable offline replay envelope remains `7.450580596923828e-09` absolute and
`3.691876147882848e-16` contribution-normalized.

The current runtime cannot prove failed-step correction persistence: the C++
worker disconnected before it returned step-14 correction data, and the
pre-C++ attempt writer was added only after this immutable run.  The source is
now hardened to fsync a `correction_attempts_pre_cpp.jsonl` record before each
worker correction call; this preserves state, forces, H and formal Q even when
a response is unavailable.  Its ordering regression passes.  This is an
evidence hardening fix, not a reclassification of this failed run.

## Moving mesh

At t=0.05 s, the actual cylinder centroids tracked the explicit one-window
transport-aligned 2-D structure displacement with maximum error
`4.4386451480291214e-13 m`.  The matching source displacement is the preceding
structure window (step 9), not step 10; z is intentionally not transported by
this 2-D preCICE interface.  The three U/p fields at t=0.05 are distinct.

The required t=0.10 snapshot does not exist because the CFD processes failed
before it was written.  Therefore the all-snapshot moving-mesh gate is FAIL,
even though the available t=0.05 evidence confirms the corrected path was
actually applied.

## Numerical failure and Courant evidence

The raw logs use `Time = ...s`, which the current V2 parser did not associate
with time records; V2 observability is consequently FAIL rather than silently
passing.  A direct raw-log extraction found the following maximum Courant
numbers before process termination:

| slice | maximum Co |
| --- | ---: |
| 0 | 19.2182085422 |
| 1 | 2.3868881992e+56 |
| 2 | 19.2667769375 |

Co first exceeded the frozen 0.5 limit at t=0.03 s and reached about 7.1 at
t=0.055 s (slices 0/2), then became catastrophic.  Slice 1 subsequently
reached `3.89e+29` and `2.39e+56`.  This is a confirmed
`SECONDARY_NUMERICAL_RISK` promoted to the current primary run blocker:
moving-mesh CFL/mesh-quality failure.  No dt, mesh, PIMPLE, damping, or
physical parameter was changed.

The 13 committed records were finite and force-chain conversion passed.  Their
mapping V2 moment and virtual-work diagnostics remained small
(`1.8519703723312414e-16` and `3.884670311502875e-16`); however the frozen
absolute mapping checks reached `1.1921292747407888e-07 N` force and
`1.1920951692423985e-07 N m` moment, so they too are recorded as failed rather
than relaxed after the run.  Newton evidence is incomplete (26 rather than 40
records) because the run stopped.

## Status and next action

`NEXT_CORRECTED_RUN = NOT_AUTHORIZED` within this task.  The next bounded task
should be a moving-mesh CFL/mesh-quality diagnosis, including the raw-log time
parser repair and the new pre-C++ attempt evidence path.  It must not start a
new CFD run until its own contract is frozen.

Raw evidence: `runtime/generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001`.
Structured gate: `results/generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001/gate.json`.

