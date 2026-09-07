# PRECiCE rollback fixture configuration fix and qualification V1

## Scope and immutable evidence

This task changed only the isolated, no-ANCF rollback fixture.  It did not
alter the deployed library, any historic runtime, the mesh, `dt`, PIMPLE,
physical parameters, or a coupled ANCF--CFD run.  The sole real callback run
is immutable at
`runtime/precice_rollback_fixture_configuration_fix_and_qualification_v1_run_001`.

The diagnostic adapter is a separately built library:

- upstream: `precice/openfoam-adapter` OpenFOAM10 commit
  `d53753b1c927b2413b02299c9da15725b3e772f0`;
- local diagnostic patch: opt-in rollback fingerprints plus a runtime build
  SHA field and mesh-point centroid;
- library: `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_003/lib/libpreciceAdapterFunctionObject.so`;
- SHA256: `cc7049e9dfc68a288146213388a2329285618f3bb3228b1efdd1a0334c0a5b16`.

## A. Minimal XML repair and configuration validation

preCICE 3.4.1 rejects a constant-waveform (`waveform-degree="0"`) exchange
unless the exchange explicitly declares whether it uses substeps.  The only
fixture XML change was to declare the frozen non-subcycled policy on the two
existing exchanges:

```xml
<exchange data="Displacement" mesh="Structure-Mesh" from="Structure" to="Fluid" substeps="false"/>
<exchange data="Force" mesh="Structure-Mesh" from="Fluid" to="Structure" substeps="false"/>
```

No waveform degree, data direction, scheme, convergence measure, or
participant name changed.  A two-participant initialization-only test used the
actual installed preCICE 3.4.1 Python binding.  Both Structure and Fluid
initialized with 40 vertices and finalized successfully:

`results/precice_rollback_fixture_configuration_fix_and_qualification_v1_config_validation_001/config_validation.json`.

`FIXTURE_CONFIGURATION = PASS`.

## B. Diagnostic OFF/ON non-intrusiveness

The frozen noncoupled 0.005 s prescribed-motion case was run once with the
diagnostic environment variable unset and once set.  Both normal runs ended
normally.  SHA256 values were exactly equal for `U`, `p`, `phi`, full mesh
points, and `forces.dat` at 0.005 s.  The force-file SHA was
`79ce70e58b53bc15c2afe19286b4efe872cce10393b3eb410fe6777fcdfcfc4f` in both
branches.

`NON_INTRUSIVE_REGRESSION = PASS`.

The comparison is intentionally noncoupled: it verifies that loading the
default-off diagnostic library and enabling its environment switch does not
change a solver result.  Callback events are instead verified by the real
preCICE fixture below.

## C. One real preCICE rollback window

The real no-ANCF fixture used `PRECURSOR_STATE_V1`, OpenFOAM 0.100 to 0.105 s,
one physical window of 0.005 s, fixed-point `min-iterations=2`,
`max-iterations=8`, and trial transverse inputs `+0.002 m`, then `-0.002 m`.
It completed with Structure and Fluid return codes zero, two coupling
iterations, one checkpoint restore, and exactly one physical commit.

Observed callback order was:

1. `CHECKPOINT_WRITE`: OF 0.100, timeIndex 0;
2. `PRE_ROLLBACK_TRIAL`: OF 0.105, timeIndex 1;
3. `POST_ROLLBACK_BEFORE_NEXT_INPUT`: OF 0.100, timeIndex 0;
4. `FINAL_COMMIT`: OF 0.105, timeIndex 1.

Thus real preCICE checkpoint/read-checkpoint callbacks occurred, and physical
time itself restored and committed exactly once.  Final finite raw cylinder
force was pressure `(542.6167070165, -47.2938883278, 0)` N plus viscous
`(705.5872173784, 1.3281018905, 0)` N, totaling
`(1248.2039243949, -45.9657864373, 0)` N.

## D. Field, mesh, and time-history identity gate

Current-value hashes at `CHECKPOINT_WRITE` and
`POST_ROLLBACK_BEFORE_NEXT_INPUT` match for `U`, `p`, `phi`, `Uf`,
`pointDisplacement`, `cellDisplacement`, full mesh points, and `oldPoints`.
Mesh-point and old-point centroids are identically
`(3.507001768228345, 0.177209983543257, 0.5)` before and after restore.
Therefore no accumulated geometric deformation was observed in this run.

However, the state identity hard gate fails:

- `meshPhi` was `NOT_OBSERVABLE_NOT_REGISTERED` at checkpoint, but was a
  persistent field after the trial and remained present after restore.  A
  state that may enter the next moving-mesh solve was therefore not restored
  to its checkpoint inventory.
- `U` and `Uf` had `old_time_levels=0` at checkpoint and `old_time_levels=1`
  after restore.  The current values hash back to the checkpoint, but the
  old-time object lifetime does not.  The trace does not establish numerical
  identity of that newly created history level.

The adapter source explains the first issue: mesh-flux checkpoint setup is
conditional on `mesh_.moving()` during checkpoint write.  At this window
start it was false, so `meshPhi` was not added to the checkpoint list; it was
created during the tentative dynamic-mesh solve.  The restore does not remove
objects created after the checkpoint.  The old-time count evidence likewise
shows that the checkpoint/restore path does not restore history existence,
only values of history levels that already exist when restore is called.

`V0` and `V00` remain `NOT_APPLICABLE_NON_SUBCYCLED`; PIMPLE outer iterations
and preCICE fixed-point iterations are not fluid subcycling.

The supplied nonzero trial data did not change `pointDisplacement` or mesh
coordinates in this one-window adapter timing path.  Consequently, although
the observed geometry did not accumulate, this run does **not** establish
distinct-input moving-geometry isolation or same-input deterministic retry.

## Final gate

| Gate | Status |
| --- | --- |
| Fixture configuration | PASS |
| OFF/ON non-intrusive regression | PASS |
| Real checkpoint and rollback callbacks | PASS |
| Current U/p/phi values after rollback | PASS |
| `Uf` current value | PASS; old-time inventory FAIL |
| `meshPhi` rollback inventory | FAIL |
| Displacement field / points / oldPoints identity | PASS for observed zero geometry |
| Time/timeIndex rollback | PASS |
| Deterministic retry with actual repeated applied motion | NOT COMPLETED |
| `ADAPTER_ROLLBACK_QUALIFICATION` | **FAIL** |

The unique first blocker is
`FIELD_ROLLBACK_IDENTITY_FAILURE`: `meshPhi` is absent at checkpoint but
persists after restore, and U/Uf old-time level counts do not return to the
checkpoint state.

`NEXT_FORMAL_ANCF_ONE_WINDOW_IMPLICIT = NOT_AUTHORIZED`.

The next scoped task should repair and independently regress the adapter
checkpoint inventory/lifetime semantics (including a dynamic-mesh state that
is registered before checkpoint), then construct a timing-correct fixture in
which each nonzero prescribed trial displacement is applied before its
tentative fluid solve.  It must not reuse this runtime or introduce ANCF.

## Evidence index

- XML initialization: `results/precice_rollback_fixture_configuration_fix_and_qualification_v1_config_validation_001/config_validation.json`
- OFF/ON reanalysis: `results/precice_rollback_fixture_configuration_fix_and_qualification_v1_off_on_003_reanalysis/off_on_regression_reanalysis.json`
- callback and field trace: `runtime/precice_rollback_fixture_configuration_fix_and_qualification_v1_run_001/adapter_rollback_trace.jsonl`
- raw fixture summary: `results/precice_rollback_fixture_configuration_fix_and_qualification_v1_run_001/real_rollback_raw.json`
- fail-closed audit: `results/precice_rollback_fixture_configuration_fix_and_qualification_v1_run_001/rollback_qualification_audit.json`
