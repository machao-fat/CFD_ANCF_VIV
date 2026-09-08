# OF10_OLDPOINTS_ROLLBACK_LIFECYCLE_CLOSURE_V1_REPORT

## Scope and immutable evidence

- No formal ANCF--CFD window, two-window qualification, or 0.05 s run was started.
- The frozen adapter remains `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib/libpreciceAdapterFunctionObject.so`, SHA256 `6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`.
- The frozen worker remains SHA256 `cb0e63116ede3c17d79e256eb1833edcdff8574d178ac1bfc81d2bcc2fad0d06`.
- The immutable two-window trace remains a failure: generation 2 checkpoint event 4 at OF time `0.105`, `timeIndex=1`; first restore event 7 passes; second restore event 9 fails only `old_points` for all three slices. The historical gate is not changed.

## OF10 source semantics and actual restore sequence

Foundation OpenFOAM 10 defines `polyMesh::oldPoints()` as follows:

- if the mesh has not moved, it returns `points()`;
- once the mesh is moving, it returns the internally owned `oldPointsPtr_`, or fatals if that pointer has not been stored;
- `polyMesh::movePoints(newPoints)` replaces `oldPointsPtr_` with the current `points_` only when `curMotionTimeIndex_ != time().timeIndex()`, then sets `points_ = newPoints` and uses `oldPoints()` to compute swept volumes;
- `polyMesh::setPoints(newPoints)` deliberately changes points *without* storing old points or returning swept volumes; and `resetMotion()` clears both `curMotionTimeIndex_` and `oldPointsPtr_`.

The active adapter stores both `meshPoints_ = mesh_.points()` and `oldMeshPoints_ = mesh_.oldPoints()` at checkpoint, but `reloadMeshPoints()` in build 006 ignores `oldMeshPoints_`. It first calls `fvMesh::move()`, whose motion-solver mover invokes `mesh().movePoints(motionPtr_->newPoints())`, then calls `fvMesh::movePoints(meshPoints_)`. After time rollback, the first motion call captures trial geometry into OF10's `oldPointsPtr_`; the second call is in the same restored `timeIndex`, so it does not replace that history. This is the exact source-level cause of the failure.

`oldPoints` is therefore a **PERSISTENT** mesh-motion history state under the frozen exact-identity contract. It participates in swept-volume/mesh-flux construction inside `polyMesh::movePoints`; it cannot be silently reclassified as a harmless diagnostic object.

## Historical numerical evidence

The immutable trace has fingerprints but no raw `oldPoints` arrays, so a direct raw-array `oldPoints` max-norm is `NOT_AVAILABLE_IN_IMMUTABLE_TRACE`. It does prove that event 9 `old_points` hash is exactly the preceding nonzero-trial `mesh_points` hash: `5e2653f775fb87f0`, rather than the generation-2 checkpoint hash `ed1aa23b4b22b94a`.

The persisted point snapshots have the same canonical identities as those two trace states, so they provide an explicitly labelled numeric proxy:

| Slice | nonzero points | max abs difference (m) | L2 difference (m) | max-difference index | delta x/y/z (m) |
|---|---:|---:|---:|---:|---|
| 0 | 16280 / 16524 | 7.9342042e-5 | 9.7318511e-3 | 8140 | (7.9342042e-5, -2.7592140e-6, 0) |
| 1 | 16280 / 16524 | 7.7584013e-5 | 9.5162167e-3 | 8140 | (7.7584013e-5, -2.6980770e-6, 0) |
| 2 | 16280 / 16524 | 7.9325622e-5 | 9.7298371e-3 | 8140 | (7.9325622e-5, -2.7586430e-6, 0) |

The reproducible read-only audit is `tools/of10_oldpoints_rollback_lifecycle_closure_v1/audit_historical_oldpoints.py`; its output is `results/of10_oldpoints_rollback_lifecycle_closure_v1/historical_oldpoints_numeric_audit.json`.

## Registry-safe candidate and controlled result

One isolated candidate, build 007, was created from the same pinned upstream plus patches 0001, 0002, 0004, 0005, and new patch 0006. It uses only public OF10 APIs:

1. `setPoints(oldMeshPoints_)`;
2. `resetMotion()`;
3. a single `movePoints(meshPoints_)`;
4. existing mesh-field checkpoint restoration.

This intentionally avoids private-member access, registry deletion, forced `meshPhi` creation, direct `pointDisplacement` writes, and a second artificial `movePoints()`. It restores the old/current geometry pair before regenerating swept volumes.

Candidate identity:

- source: pinned `precice/openfoam-adapter` OpenFOAM10 commit `d53753b1c927b2413b02299c9da15725b3e772f0` plus patches 0001/0002/0004/0005/0006;
- library: `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_007/lib/libpreciceAdapterFunctionObject.so`;
- SHA256: `ec5fe81595c5a94a1436d8e907a02af828236b4d96d968c291f5052afc37e8fe`;
- build/link validation: PASS (`ldd -r` has no unresolved symbols).

The one permitted fresh no-ANCF prescribed-motion fixture used `dt=0.005 s`, one physical window, initial/first repeated `+0.002 m` and distinct `-0.002 m` transverse trial schedule. At its first restore, checkpoint and restored `old_points` identities both equal `ed1aa23b4b22b94a`: the direct old-points identity repair works. However, the subsequent tentative CFD solve fatals before the second restore with:

```
FOAM FATAL ERROR: V0 is not available
Foam::fvMesh::V0() -> Foam::fvMesh::Vsc0() -> EulerDdtScheme::fvmDdt()
```

Removing the former `fvMesh::move()` also removed the normal OF10 `fvMesh::move()` lifecycle update of `curTimeIndex_`; consequently the next physical motion did not establish the volume history needed by `fvm::ddt`. This is a genuine unsafe interaction with the mesh volume-history lifecycle, not an ANCF, force, or coupling-algorithm result. The fresh runtime is retained immutable at `runtime/of10_oldpoints_rollback_lifecycle_closure_v1_run_001`.

No further candidate, retry, or numerical workaround was run.

## Decision

| Gate | Status | Basis |
|---|---|---|
| `OLDPOINTS_ROOT_CAUSE` | `CONFIRMED` | build-006 adapter ignores stored `oldMeshPoints_`; `fvMesh::move()` plus subsequent `movePoints()` leaves trial geometry in OF10 `oldPointsPtr_`. |
| `OLDPOINTS_RESTORE_SEMANTICS` | `PERSISTENT` | OF10 uses the old/current point pair for swept-volume motion semantics; frozen exact identity applies. |
| `REGISTRY_SAFE_FIX` | `FAIL` | candidate 0006 restores oldPoints but fails the necessary OF10 `V0` lifecycle before another CFD solve. |
| `ROLLBACK_REPLAY_QUALIFICATION` | `FAIL` | build 007 cannot complete same-input/different-input replay after the first restore. |
| `NEXT_IMPLICIT_0P05S` | `NOT_AUTHORIZED` | no qualified, registry-safe solution preserves both oldPoints and V0 histories. |

The minimum next action is an explicit design review of an OF10-supported way to restore the coupled `oldPoints`/`curMotionTimeIndex_`/`V0` state as one lifecycle unit. It must not use private-memory access, registry deletion, extra fabricated motion, or an unreviewed weakening of the oldPoints identity contract. Only after that design is accepted should a new isolated no-ANCF lifecycle fixture be authorized; a formal two-window run remains outside this task.
