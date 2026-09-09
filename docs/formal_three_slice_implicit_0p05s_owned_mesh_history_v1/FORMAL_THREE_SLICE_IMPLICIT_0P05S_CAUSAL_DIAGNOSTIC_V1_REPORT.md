# Formal three-slice implicit 0.05 s causal diagnostic V1

## Decision and scope

This is a read-only analysis of immutable runtime
`runtime/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001`.
It did not start a participant, OpenFOAM, ANCF, or preCICE and did not change
the OF10 restore, adapter, ANCF, preCICE configuration, mesh, `dt`, PIMPLE,
containment, or physics.

```
IMPLICIT_0P05S = FAIL_CLOSED (immutable)
LAST_COMMON_COMMITTED_OF_TIME = 0.145 s
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

The first hard stop remains Structure containment at window 10, trial 3,
`tau=0.050 s`: raw Structure-side `Fx` was `-2083602.4229046283 N` on slice 0
and `-2084484.997346848 N` on slice 2, above the frozen `2.0e6 N` limit.
Nothing here reclassifies the rejected window or CFD `.150 s` files as a
coupled physical state.

## Proven event order

On each accepted window, a fresh force is seen only at trial 3; trials 1--2
reuse the preceding accepted integrated force.  The participant source order
is:

```
prior accepted force -> ANCF predict -> write Displacement -> CFD/preCICE advance
-> read new Force -> containment -> ANCF correction -> rollback or commit
```

The containment branch occurs before `map_integrated_slice_forces()`, the
correction, `records.append()`, `adapter.finalize_committed()`, and `cp.commit()`
in `tools/checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1/implicit_structure_participant.py`.

| accepted window | tau [s] | slice-0 raw Fx [N per 1 m] | slice-0 integrated Fx [N] | ux [m] | vx [m/s] |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | .005 | 1,248 | 20,803 | 1.664e-05 | 6.657e-03 |
| 2 | .010 | -990 | -16,494 | 4.375e-05 | 4.188e-03 |
| 3 | .015 | 4,763 | 79,381 | 1.101e-04 | 2.234e-02 |
| 4 | .020 | -8,898 | -148,300 | 1.390e-04 | -1.077e-02 |
| 5 | .025 | 24,034 | 400,574 | 3.081e-04 | 7.844e-02 |
| 6 | .030 | -54,898 | -914,972 | 1.863e-04 | -1.272e-01 |
| 7 | .035 | 135,439 | 2,257,315 | 8.146e-04 | 3.785e-01 |
| 8 | .040 | -321,864 | -5,364,403 | -2.987e-04 | -8.238e-01 |
| 9 | .045 | 806,313 | 13,438,556 | 3.220e-03 | 2.231 |

The first clear force departure is window 3/trial 3 (`tau=.015 s`), from the
roughly 1 kN raw scale to +4.76 kN.  The observed alternating escalation then
continues through window 9; it is not first created at containment.

## Force, motion, and Co

The slice-0 fluid log shows pressure-dominated streamwise force:

| CFD time [s] | pressure Fx [N] | viscous Fx [N] | total Fx [N] | max Co |
| ---: | ---: | ---: | ---: | ---: |
| .140 | 133,743.9 | 1,695.0 | 135,438.9 | .551 |
| .145 | -319,756.8 | -2,107.4 | -321,864.2 | .286 |
| .150 (tentative CFD output) | 799,833.0 | 6,480.3 | 806,313.3 | 1.464 |

The first observed Co breach is at CFD `.140 s` (`.5505 > .5`), at the same
fluid stage as the 135 kN raw force.  Co, pressure force and mesh motion are
outputs of the same CFD trial, so the trace does not establish their ordering
inside that solve.  It is invalid to claim either that Co caused force or that
force alone caused Co.

The supported mechanism is **deterministic closed-loop force--motion
amplification**, not a proven one-way added-mass or VIV mechanism: prior force
creates predictor motion; CFD returns the next pressure-dominated force; that
force would correct the structure.  At window 10 it is rejected immediately
after the new force is read, before correction and common commit.

The retained preconditioned-force audit is compatible with this interpretation:
recorded-force ANCF replay reproduced its structural source exactly;
recorded-motion CFD replay reproduced the escalating force to below 0.4% of
each slice force range; mesh-only replay kept 20/20 meshes valid.  These are
one-way reproducibility facts, not proof of physical VIV or implicit-scheme
stability.

## Checks made and limits

No accepted-window record supports double tributary length, raw/integrated
unit-conversion, or stale/default-force use: Force Contract and Generalized
Force V2 passed and records preserve the 1 m raw to 16.666... m integrated
conversion.  The window-10 same-event identity between OpenFOAM
`cylinderForces` and rejected Structure raw `-2.0836 MN` was not recorded.
Those values must not be treated as guaranteed identical representations.
This is a rejected-trial observability gap, not proof of a sign/unit/mapping
or time-layer defect.

Each fluid trace records 10 `FINAL_COMMIT` events, but Structure records nine
physical commits.  The tenth fluid event is that participant reaching its
configured time horizon; Structure receives its force and throws containment
before accepted-record write, ANCF finalization, and checkpoint commit.  The
only common restart/analyzable state is window 9 at OF `.145 s`; CFD `.150 s`
is participant-local/tentative.  No double Structure commit is observed.

## Independent history-observability gap

Read-only result
`results/formal_three_slice_implicit_0p05s_causal_diagnostic_v1_run_002/causal_diagnostic.json`
confirms current-value and `old_points` identity at every inspected restore.
It remains fail-closed for persistent U/Uf oldTime: traces retain layer counts
but no oldTime value fingerprint.  This is
`PERSISTENT_HISTORY_NOT_OBSERVABLE`, not a proven containment cause.

For demonstrated generation 2, owner meshPhi is present at checkpoint and
restore with equal count `24226` and hash `f4f527555e12d051`, classified
`OWNER_NON_LAZY`.  The generic correlation helper reports
`UNSUPPORTED_MESHPHI_LIFECYCLE` because it recognizes only selected class
labels, not because raw meshPhi evidence differs.  Historical audit JSON is
unchanged.  An invalid auxiliary diagnostic run `001`, whose parser captured
force moments, is retained; run `002` corrects the parser without touching
runtime evidence.

## One minimal next experiment -- proposal only

Authorize at most one `WINDOW10_PREDICTOR_FORCE_IDENTITY_REPLAY_V1`, starting
only from common accepted window-9 state.  Regenerate the W10 predictor using
that state and its accepted prior force, then run one prescribed-motion CFD
step of `.005 s`.  Bind one transaction ID to predictor motion, OpenFOAM
`cylinderForces`, Fluid-Mesh data, mapped Structure-Mesh data, and raw plus
integrated ANCF force.  It must not consume rejected `.150 s` Structure state
or change mesh, `dt`, PIMPLE, damping, containment, or tolerances.

A transaction-consistent conversion and reproduction of W10 force would move
the question to physical/algorithmic feedback.  A mismatch would identify a
production mapping, unit, sign, or time-layer defect.  This experiment is not
authorized or executed by this review.

## Retained result

Nine committed windows, their ANCF/IPC identities, accepted mapping, and final
three-slice mesh checks remain valid bounded numerical evidence.  They are not
VIV validation and do not authorize restart from `.150 s`, a new `.05 s` run,
or any long VIV calculation.
