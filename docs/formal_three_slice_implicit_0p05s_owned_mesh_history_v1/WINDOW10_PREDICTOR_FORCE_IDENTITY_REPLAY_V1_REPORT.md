# WINDOW10 Predictor–Force Identity Replay V1

## Scope and immutable source

This is the one authorized prescribed-motion replay of the rejected tenth
window from `formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001`.
It is not a re-run of the 0.05 s coupled calculation.  The source run remains
`FAIL_CLOSED`; its last common accepted state is OF `0.145 s`, and its W10
Structure correction/physical commit remain unexecuted.

The replay runtime is
`runtime/window10_predictor_force_identity_replay_v1_run_003`.  It uses the
same isolated Foundation OF10 owner-diagnostic ABI and the same adapter
identity `c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17`.
No rejected source `0.150` field, mesh, or Structure state was copied.

Two preparation-only directories are retained separately.  `run_001` stopped
before CFD because Windows Python cannot execute the frozen Linux worker.
`run_002` stopped before CFD because a new resident worker correctly rejects a
direct first W10 transport frame (`sequence=1` requires `bridge=1`).  The
successful preparation starts a legal new transport segment at W9 while
retaining physical global step 10.  These are environment/transport facts, not
CFD or ANCF numerical trials.

## Recovery and predictor identity

The accepted W9 checkpoint is
`checkpoints/window_000010_checkpoint.{json,cpp.json}`.  It has committed
global step 9, physical time `0.045 s`, complete ANCF `q/qdot/qddot`, and the
three accepted integrated slice forces.  Its C++ checkpoint SHA256 is
`399f3a9ad94d494c624868b16cec59f6f9d95413882ccad1c2311ca0344aac1b`.

Every slice has a W9 `0.145` restart directory containing `U`, `Uf`, `p`,
`phi`, `meshPhi`, `pointDisplacement`, `cellDisplacement`, and
`polyMesh/points`.  The formal adapter trace also records the W10
`POST_ROLLBACK_BEFORE_NEXT_INPUT` state at OF `0.145`, including U/Uf,
point-displacement, mesh-point, and owner-history fingerprints.  Restart is
therefore limited to the already-qualified current Foundation OF10
Euler/non-subcycled lazy-history semantics; it is not a new claim about
multi-step formats or the separate persistent-oldTime observability gap.

The original W10 prediction response hash is
`53bb18a01d709d5c21218729630e2955bdf2e69046d6a63d3d70191d8eb6c411`.
Recomputing it from the saved W9 physical state and prior accepted forces gave
the identical full response hash.  This hash covers the full ANCF response
arrays, not a displacement centroid.  The frozen pure projection then produced
all 40 ordered `[ux, uy]` vectors for each `Structure-Mesh`; their payload
hashes are recorded in `payloads.json`.

The W10 predictor interface motion was nonzero:

| Slice | ux (m) | uy (m) | vx (m/s) | vy (m/s) |
| --- | ---: | ---: | ---: | ---: |
| 0 | 0.0327502498341 | -0.00207124514612 | 9.58102353283 | -0.611684665787 |
| 1 | 0.0216943640406 | -0.00135706333881 | 6.51767056079 | -0.416213076422 |
| 2 | 0.0327598505295 | -0.00207203636283 | 9.58427529351 | -0.611894017758 |

The test participant first supplied the accepted W9 interface state when
preCICE requested initial data, then supplied this complete W10 predictor
payload on each trial.  It did not invoke ANCF correction, containment
override, or physical commit.

## Single replay transaction

Transaction ID: `WINDOW10_PREDICTOR_FORCE_IDENTITY_REPLAY_V1/run_001`.

The replay uses real preCICE and the real adapter, with OF `0.145→0.150 s`,
`dt=0.005 s`, production PIMPLE/mesh/physics, and preCICE min/max iterations
`2/8`.  Only the test runtime, preCICE duration (`0.005 s`), start time, and
socket directory differ from the immutable run.  All six participants exited
zero.  The third implicit iteration carried the nonzero force; the first two
read the initialized zero force in this prescribed participant configuration.

| Slice | cylinderForces pressure (N), x/y | viscous (N), x/y | Fluid total (N), x/y | Structure received raw (N), x/y | max Co |
| --- | --- | --- | --- | ---: |
| 0 | -2070537.5594 / 141211.614015 | -13064.8635039 / 746.124489476 | -2083602.42290390 / 141957.738504476 | -2083602.42290636 / 141957.738504029 | 1.46356946865 |
| 1 | -1352333.12989 / 91825.6601507 | -8983.10685176 / 545.433401276 | -1361316.23674176 / 92371.093551976 | -1361316.23673756 / 92371.093551975 | 1.14257187048 |
| 2 | -2071415.56850 / 141270.582371 | -13069.428839 / 746.335179474 | -2084484.99733900 / 142016.917550474 | -2084484.99733852 / 142016.917550071 | 1.46400134025 |

The replay's Fluid-to-Structure component discrepancies are at most
`4.21e-6 N` in x and `4.47e-7 N` in y.  For the two values actually preserved
by the original containment event, replay versus original differs by
`1.73e-6 N` (slice 0 x) and `8.33e-6 N` (slice 2 x), respectively.

The `LoadRecord` conversion passed for all three slices using the frozen
`1 m` unit span and the existing tributary lengths (`16.666... m` per slice).
It yielded the expected integrated slice-force representation and a formal
generalized-force vector.  Generalized Force V2 is deliberately
`NOT_EVALUABLE_NO_ANCF_CORRECTION_AUTHORIZED`: evaluating its C++ side would
require precisely the rejected ANCF correction that this task forbids.

The normal formal runtime's ordinary `.150` `cylinderForces` write is not used
as the comparison event.  That process was interrupted after Structure read
the containment force; its logged write belongs to a different function-object
phase.  The replay, which completed its participant-local preCICE exchange,
retains the final cylinder-force write and directly links it to the Structure
force payload under the single replay transaction ID.

## Result and limits

Numerically, the chain

`W10 predictor displacement → cylinderForces → Fluid-Mesh Force → preCICE → Structure-Mesh Force → raw slice force → LoadRecord/generalized mapping`

is consistent in the replay, and the two immutable original containment
components reproduce.  Thus:

```text
CROSS_CHANNEL_FORCE_IDENTITY_NUMERIC_OBSERVATION = PASS
WINDOW10_FORCE_RESPONSE_NUMERIC_OBSERVATION = REPRODUCIBLE
```

The requested comparator tolerance was not serialized in `preflight.json`
before execution.  The post-execution audit uses `1e-5 N` absolute or `1e-11`
relative only to make the arithmetic reproducible; it cannot be represented as
a predeclared acceptance gate after the fact.  Therefore the stricter labels
remain deliberately conservative:

```text
CROSS_CHANNEL_FORCE_IDENTITY = NOT_EVALUABLE_STRICT_PREDECLARED_TOLERANCE_MISSING
WINDOW10_FORCE_RESPONSE = NOT_EVALUABLE_STRICT_PREDECLARED_TOLERANCE_MISSING
```

This is a test-governance limitation, not evidence of a force sign, unit-span,
tributary-length, preCICE mapping, or rejected-state contamination error in
the observed W10 chain.  It also does not establish added-mass instability,
physical VIV, or long-time stability.  The large W10 predictor motion and the
reproducible pressure-dominated force remain evidence that the next work
belongs in independently interpretable baseline studies: fixed-cylinder CFD,
ANCF free vibration, prescribed-motion force characterization, and then an
independent single-slice free-FSI baseline.

`PERSISTENT_HISTORY_NOT_OBSERVABLE` remains a separate historical
qualification item and is not assigned as the containment cause.

## Evidence and authorization

- Preparation/input proof: `runtime/window10_predictor_force_identity_replay_v1_run_003/preflight.json` and `payloads.json`
- Runtime transaction evidence: `runtime/window10_predictor_force_identity_replay_v1_run_003/structure_000{0,1,2}_transaction.json`, fluid traces, and stdout
- Read-only audit: `results/window10_predictor_force_identity_replay_v1_run_001/window10_predictor_force_identity_replay_audit.json`
- Audit SHA256: `7fda5bf73ad33ee1cfd819473243765fbc99ef56366ec22d2750195f6d47625c`

```text
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```
