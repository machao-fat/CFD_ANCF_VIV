# U/Uf oldTime lifecycle contract decision V1

## Scope and immutable record

This is a read-only supplemental qualification of the immutable runtime
`runtime/formal_three_slice_owned_mesh_history_two_window_v1_run_001`. It
addresses only `U_UF_OLDTIME_LIFECYCLE_IDENTITY_FAILURE` for the Foundation
OpenFOAM 10 Euler, non-subcycled dynamic-pimpleFoam path. It changes neither
the runtime nor the frozen `EXACT_HISTORY_INVENTORY` gate.

The original result remains:

```
FORMAL_IMPLICIT_TWO_WINDOW = FAIL
```

The legacy auditor's `states.old_points` schema error also remains immutable.
The owner-observability trace records that state at
`states.owner_mesh_history.old_points`; it is not a retrospective rewrite of
the old auditor.

## Direct production lifecycle

The production candidate adapter records the checkpoint time in
`Adapter::storeCheckpointTime()` and restores it with `Time::setTime()` in
`Adapter::reloadCheckpointTime()` (`Adapter.C`, lines 1064-1079). Its
`readCheckpoint()` order is:

1. restore checkpoint Time;
2. restore owner-managed mesh history;
3. restore generic fields, including `volVectorField U` and
   `surfaceVectorField Uf` (`Adapter.C`, lines 1397-1480).

At checkpoint write, the generic U and Uf copy loops copy only the current
field contents (`Adapter.C`, lines 1634-1638 and 1658-1662). In generation 1,
the immutable trace records zero old-time levels for both fields at the
checkpoint in all three slices:

| field | checkpoint current hash | checkpoint levels | restore current hash | restore levels |
| --- | --- | ---: | --- | ---: |
| U | `a62c359644bb728c` | 0 | `a62c359644bb728c` | 1 |
| Uf | `880ec3e4dd3d6d85` | 0 | `880ec3e4dd3d6d85` | 1 |

The trace deliberately did not call `oldTime()` merely to inspect it, so it
does not contain old-field values. Generation 2 already has one old-time
level at checkpoint and both restores retain the recorded level and current
field identities; it is governed by the exact-history rule, not the derived
rule below.

## Source-level numerical mechanism

`GeometricField::operator==` performs content assignment through `ref()` and
`boundaryFieldRef()` (Foundation OF10 `GeometricField.C`, lines 1591-1605).
Both accessors call `storeOldTimes()` (lines 1012-1042). If an old field
already exists and its time index differs from the restored Time, that method
first snapshots the live field into the old field, then corrects the live
field's time index (lines 1055-1088).

For generation 1, the trace first proves that live U and Uf old fields exist
at the rejected trial time index 1. The actual dynamic-pimpleFoam loop calls
`runTime++`, moves the mesh, then includes `UEqn.H`; its first field-specific
Euler demand is `fvm::ddt(U)`. That demand calls `U.oldTime()`. The later
pressure equation calls `fvc::ddtCorr(U, phi, Uf)`, whose Euler implementation
calls both `Uf.oldTime()` and `U.oldTime()`. Thus the first documented
field-specific sources of the two lazy layers are the U equation and then the
pressure correction, respectively. On rollback, the adapter first resets Time
to checkpoint index 0. The generic current-field assignment therefore
temporarily stores the rejected live current value in the existing old field.
It then observes one old-time level and executes the generic old-field
assignment. The checkpoint copy has no old field, so the right-hand
`checkpointCopy.oldTime()` creates a full copy of its checkpoint current
field at restored Time index 0 (`GeometricField.C`, lines 1108-1131). The
second assignment overwrites the temporary rejected value. Thus the live
old field after the complete generic restore is the checkpoint current field,
not rejected-trial data.

This is numerically material: `pimpleFoam/UEqn.H` uses `fvm::ddt(U)`, and
Euler `fvmDdt` consumes `U.oldTime()` with moving-mesh volume history.
`pimpleFoam/pEqn.H` calls `fvc::ddtCorr(U, phi, Uf)`; Euler's
`fvcDdtUfCorr` explicitly consumes both `Uf.oldTime()` and `U.oldTime()`.
The derived layer therefore must be demonstrated numerically rather than
treated as an unimportant cache.

## No-CFD numerical reproduction

`uUfOldTimeLifecycleProbe` reads only the formal slice-0000 `0.1` fields and
mutates local, unregistered U/Uf copies. It executes the same generic restore
ordering with a rejected trial perturbation `(1,-2,0.5)`. The formal case has
no persisted `0.1/Uf`; as in OF10 `createUfIfPresent.H`, the probe constructs
Uf as `fvc::interpolate(U)`. It does not run a CFD solve or modify the case.

Valid parseable evidence is
`results/formal_three_slice_owned_mesh_history_two_window_v1_run_001/u_uf_oldtime_lifecycle_probe_003.json`.
The isolated executable SHA256 is
`11e74c26182baad504b50ce47bb8689bdd131879f54e3116b1f8399c93e79a10` and its
`ldd -r` closure resolves libOpenFOAM, libfiniteVolume and libmeshTools from
the owner-diagnostic ABI prefix only.

| field | values compared | current vs checkpoint | restored old vs checkpoint current | restored old vs rejected trial | restored current/old timeIndex |
| --- | ---: | ---: | ---: | ---: | --- |
| U | 16,524 | max=0, L2=0 | max=0, L2=0 | max=2, L2=292.02910813821285 | 0 / 0 |
| Uf | 24,506 | max=0, L2=0 | max=0, L2=0 | max=2, L2=356.63216344014739 | 0 / 0 |

For both fields the local reproduction has exactly one level before and after
the generic old-field assignment. The rejected-trial comparison is nonzero,
which rules out trial contamination. The preliminary raw-Uf reader failure
and a JSON-only quoting defect are retained as probe setup evidence; neither
is used as a numerical result. Probe `003` is the valid result.

## Versioned limited acceptance contract

`DERIVED_LAZY_NUMERICALLY_EQUIVALENT_U_UF_OLDTIME_V1` accepts a `0 -> 1`
inventory transition only when every condition below holds:

1. At checkpoint, the field has zero old-time levels.
2. The adapter restores Time to the checkpoint value and index before generic
   current-field assignment.
3. The field follows the exact OF10 generic U/Uf restore branch documented
   above; the complete branch, including old-field assignment, runs once.
4. The lazily created checkpoint-copy old field is a complete numerical copy
   of checkpoint current values, with the checkpoint time index.
5. The restored live old field is numerically equal to that checkpoint current
   copy and distinguishable from rejected-trial data.
6. The next real Euler moving-mesh solve consumes the history without a state
   or numerical hard failure. The formal run did so and all Structure/IPC,
   force, GF V2, Newton, Quality V4 and checkMesh gates passed.

This contract is limited to Foundation OF10, the frozen adapter candidate,
Euler, no temporal subcycling, this U/Uf dynamic-pimpleFoam path, and a
checkpoint whose U/Uf old-time inventory is initially zero. It excludes
nonzero or multi-level histories, V00/multi-step and higher-order schemes,
subcycling, altered restore ordering, different field construction paths, and
any path that accesses oldTime before rollback completion. Those cases retain
`EXACT_HISTORY_INVENTORY` unless separately qualified.

## Decision

```
U_UF_OLDTIME_LIFECYCLE_SUPPLEMENTAL_QUALIFICATION =
PASS_FOR_CURRENT_EULER_NON_SUBCYCLED_SCOPE
```

The former identity mismatch is explained by a lawful lazy-layer creation,
not a rejected-trial leak or an OF10-owned mesh-history restore defect. The
frozen exact-inventory result is intentionally not changed. No production
adapter, ANCF, IPC, OF10-owned mesh-history implementation, physical setting,
mesh, dt, PIMPLE setting or coupling tolerance was modified for this review.

The evidence supports requesting human review for one controlled 0.05 s
continuation on the same baseline. It does not authorize that run itself:

```
NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED_PENDING_HUMAN_REVIEW
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED_PENDING_HUMAN_REVIEW
```
