# OPENFOAM10_CHECKPOINT_LIFECYCLE_AND_MOTION_TIMING_CLOSURE_V1

## Decision

`ADAPTER_ROLLBACK_QUALIFICATION = FAIL`.

The single permitted fresh no-ANCF qualification runtime is immutable at
`runtime/openfoam10_checkpoint_lifecycle_motion_timing_closure_v1_run_001`.
It aborted during initial checkpoint construction, before a CFD physical solve,
preCICE callback trace, rollback, or physical commit. No retry was performed.

`NEXT_FORMAL_ANCF_ONE_WINDOW = NOT_AUTHORIZED`.

## Diagnostic build

| Item | Value |
| --- | --- |
| Upstream | `precice/openfoam-adapter`, `OpenFOAM10` |
| Commit | `d53753b1c927b2413b02299c9da15725b3e772f0` |
| Patch chain | target-dir; fingerprint diagnostic; rejected lifecycle/motion `0003` |
| Environment | Foundation OF10 `/opt/openfoam10`; GCC 11.4; preCICE 3.4.1 |
| Library | `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_004/lib/libpreciceAdapterFunctionObject.so` |
| SHA256 | `864629309d95647ae60b824b241f8252925941115a77c0f40ce761dd7666867c` |
| Build/link audit | PASS; `ldd -r` has no missing library or unresolved symbol |

The `.004` library is a diagnostic candidate, not a qualified adapter baseline.

## Lifecycle root cause and rejected candidate

The pinned source creates mesh checkpoint fields in `storeMeshPoints()` only
when `mesh_.moving()` is already true. At a window-start checkpoint it is
false, so `setupMeshCheckpointing()` is skipped. A later dynamic-mesh trial
creates `meshPhi`; restore has no checkpoint inventory for it. This is the
direct cause of the prior `meshPhi` existence mismatch.

The candidate patch tried to register `meshPhi` before the checkpoint by
unconditionally calling `setupMeshCheckpointing()`. Foundation OF10 rejects
this: `fvMesh::phi()` fatals before the mesh is moving:

```
mesh flux field does not exist, is the mesh actually moving?
From Foam::fvMesh::phi() const, fvMeshGeometry.C:499
```

Therefore that patch is rejected. It is not an accepted `meshPhi` fix. The
next task must use an OF10-registry-safe existence-inventory restore, or an
OF10-supported lifecycle hook that creates meshPhi only after legal
mesh-motion initialization.

The pinned adapter also checkpoints only current field values. After a
tentative solve creates `oldTime()`, `readCheckpoint()` calls `oldTime()` and
therefore changes a zero-level checkpoint into one level. The candidate uses
guarded normal `GeometricField::oldTime()` initialization before checkpointing
and copies old-time numeric values; it does not modify registry ownership or
history counters. It was never runtime-qualified because meshPhi aborted first.
Thus `HISTORY_LIFETIME = NOT_COMPLETED`.

## Motion timing finding

Source tracing found `initialize()` did not call `readCouplingData()`, while
the misleadingly named `adjustSolverTimeStepAndReadData()` only sets the
allowed timestep. The prior `+/-0.002 m` fixture consequently never entered
the FSI displacement reader before a solver step.

The candidate reads initial coupling data after preCICE initialization and
after each `advance()`/restore. The fixture uses Displacement
`initialize="yes"` and intended `+A, +A, -A, -A` trials. This was not executed:
the first checkpoint abort preceded any solve. Therefore
`MOTION_FIXTURE_TIMING = NOT_COMPLETED`.

## Non-intrusive regression

`runtime/openfoam10_checkpoint_lifecycle_motion_timing_closure_v1_off_on_003`
used `.004` with diagnostic fingerprints OFF and ON under the existing nonzero
prescribed-motion fixture. Both runs returned zero and had identical SHA256
for `U`, `p`, `phi`, full mesh `points`, and `cylinderForces/forces.dat`.

`NON_INTRUSIVE_REGRESSION = PASS` for fingerprint instrumentation only.

## Gate ledger

| Gate | Status |
| --- | --- |
| CHECKPOINT_LIFECYCLE | FAIL |
| MOTION_FIXTURE_TIMING | NOT_COMPLETED |
| FIELD_ROLLBACK_IDENTITY | NOT_EVALUABLE |
| HISTORY_LIFETIME | NOT_COMPLETED |
| MESH_ROLLBACK_IDENTITY | NOT_EVALUABLE |
| NONZERO_MOTION_ISOLATION | NOT_EVALUABLE |
| DETERMINISTIC_RETRY | NOT_EVALUABLE |
| TIME_COMMIT_IDENTITY | NOT_EVALUABLE |
| V0/V00 non-subcycled policy | PASS |
| ADAPTER_ROLLBACK_QUALIFICATION | FAIL |

First blocker: `OF10_MESHPHI_PRECHECKPOINT_LIFECYCLE_FAILURE`.

No ANCF-CFD one-window or longer coupled run is authorized. The only prudent
next task is an adapter-only OF10 meshPhi registry-lifecycle study followed by
a separately authorized fresh no-ANCF qualification.
