# preCICE Time-Layer Contract and Different-Input Rollback Closure V1

## Decision

`ADAPTER_ROLLBACK_QUALIFICATION = PASS` for the reproducible diagnostic
adapter `d53753b1c927b2413b02299c9da15725b3e772f0 + patches 0001, 0002, 0005`
in the frozen non-subcycled, no-ANCF one-window fixture. `NEXT_FORMAL_ANCF_ONE_WINDOW = CONDITIONAL`: use this exact library and the already-qualified checkpoint-aware Structure participant; do not use the legacy deployed library, and do not extend the duration automatically.

## preCICE 3.4.1 time semantics and source audit

For `readData(..., relativeReadTime)`, zero denotes the beginning of the
current time step and `dt` its end. The pure two-participant regression
(`precice_time_layer_contract_v1_regression_002`) observed the sequence
`start=+0.002`, `end_1=+0.002`, `end_2=-0.002` with `relativeReadTime=0.005`.
This proves that the next trial sample is not the window-start sample.

The active Python backend at
`src/coupling/precice_adapter_v1/precice_backend.py:74-84` follows
`write Displacement -> advance(dt) -> read Force(0)`. This is valid: after
the Structure participant has advanced, zero refers to the just-reached force
time. The explicit and checkpoint-aware Structure launchers use the same
post-advance Force-read ordering. No extra Structure lag was found.

The OpenFOAM adapter needs a different read placement: after `advance()` has
requested rollback, the OpenFOAM state is restored to the window start but the
next input belongs to the completed window end. Patch 0004 incorrectly read
`0.0` there. Patch 0005 changes only that call to
`precice_->getMaxTimeStepSize()`. Initial-data reading remains `0.0` after
`initialize()`. Thus `PRODUCTION_TIME_LAYER_AUDIT = PASS` for the future,
source-pinned adapter path. The legacy deployed adapter remains
`NOT_EVALUABLE`, because its source is unrecovered; no historical conclusion
is retroactively changed.

## Fixture correction and non-CFD regression

The minimal code change is one adapter call site:

```cpp
readCouplingData(precice_->getMaxTimeStepSize());
```

It is in `Adapter::execute()` after `advance()`, checkpoint restore/write, and
before the next tentative solve. No waveform degree, coupling scheme,
convergence limit, exchange direction, timestep, or physical setting changed.
The pure preCICE regression passed three iterations and two read-checkpoint
events. The discarded configuration-only regression run `_001` failed before
participant initialization because its Force exchange mesh was invalid; it is
preserved. The corrected `_002` is the valid result.

The patch-0005 diagnostic OFF/ON regression passed with identical SHA-256
files for `U`, `p`, `phi`, mesh points, and `forces.dat`; it used the frozen
small prescribed-motion fixture and did not enable callback tracing in the
OFF branch.

## Real no-ANCF one-window qualification

Fresh immutable runtime:
`runtime/precice_time_layer_contract_different_input_rollback_closure_v1_run_001`.
It used `PRECURSOR_STATE_V1`, OpenFOAM `0.100 -> 0.105 s`, one physical window,
and the frozen `minIterations=2`, `maxIterations=8` fixed-point contract.
The callback trace contains exactly one `CHECKPOINT_WRITE`, two
`PRE_ROLLBACK_TRIAL` / `POST_ROLLBACK_BEFORE_NEXT_INPUT` pairs, and one
`FINAL_COMMIT`. Physical time and `timeIndex` restored to `0.100 s, 0` after
each rollback and committed once at `0.105 s, 1`.

The initial and first two trial inputs were `+0.002 m`; both positive trials
had identical canonical current-field and full-mesh fingerprints. Their full
mesh centroid was `(3.5070017682, 0.1778611381, 0.5)`. The corrected post-
advance read then delivered `-0.002 m`; the final converged trial centroid was
`(3.5070017682, 0.1765588289, 0.5)`. Both differ from the checkpoint centroid
`(3.5070017682, 0.1772099835, 0.5)` with opposite signs. Therefore both
prescribed inputs entered the normal preCICE-to-adapter motion path and trial
two did not accumulate trial one's deformation.

Checkpoint-to-restore exact identities passed for `U`, `p`, `phi`, `Uf`,
`cellDisplacement`, full mesh points, time, and timeIndex. `meshPhi` is absent
at the checkpoint and is legally reconstructed after `movePoints()`. `U/Uf`
old-time levels are lazily created; their restored numerical values equal the
checkpoint current values. `pointDisplacement` and `oldPoints` are derived
motion/history objects during OF10 mesh reconstruction, so their object
inventory differs after restore. They are not treated as persistent copies:
the same-input retry reproduced the exact next-trial `U/p/phi`,
`pointDisplacement`, `cellDisplacement`, mesh, and force input; the different
input produced the corresponding opposite geometry. `V0/V00` remain
`NOT_APPLICABLE_NON_SUBCYCLED`.

No NaN, FPE, negative cell, cumulative mesh deformation, or second physical
commit occurred. The final committed force is fixture-only evidence, not an
ANCF–CFD hydrodynamic result: pressure `(602.6026006673, 61261.08075349, 0)` N,
viscous `(704.7704353911, 702.9772731850, 0)` N, total
`(1307.3730360584, 61964.0580266706, 0)` N.

## State gates

| Gate | Status |
| --- | --- |
| `TIME_LAYER_CONTRACT` | PASS |
| `PRODUCTION_TIME_LAYER_AUDIT` | PASS for the source-pinned future path; legacy library NOT_EVALUABLE |
| `FIXTURE_TIME_LAYER_REGRESSION` | PASS |
| `NONZERO_MOTION_ISOLATION` | PASS |
| `FIELD_HISTORY_EQUIVALENCE` | PASS: persistent identity or verified deterministic reconstruction |
| `MESH_ROLLBACK` | PASS |
| `DETERMINISTIC_RETRY` | PASS |
| `ADAPTER_ROLLBACK_QUALIFICATION` | PASS |

## Historical evidence disposition

No legacy runtime or report changed. ANCF core validation, force scaling,
H/H-transpose mapping, independent fixed/controlled CFD tests, and current
source-pinned rollback qualification remain valid within their respective
contracts. Historical coupled trajectories produced with the unrecovered
legacy adapter are not retroactively time-layer-validated; any future use of
their coupled stability interpretation requires a separate source-provenance
or repeat-evidence decision.
