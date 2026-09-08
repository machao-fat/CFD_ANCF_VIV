# OF10_MESH_HISTORY_ATOMIC_RESTORE_DESIGN_REVIEW_V1_REPORT

## Scope and frozen evidence

This is a read-only design review. No adapter source, OpenFOAM source, build, CFD/ANCF run, lifecycle fixture, historical runtime, or existing gate was changed.

| Item | Frozen identity / disposition |
|---|---|
| Active reproducible adapter, build006 | `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib/libpreciceAdapterFunctionObject.so`; SHA-256 `6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973` |
| Rejected candidate, build007 | SHA-256 `ec5fe81595c5a94a1436d8e907a02af828236b4d96d968c291f5052afc37e8fe`; retained as immutable rejected experiment |
| C++ worker | SHA-256 `cb0e63116ede3c17d79e256eb1833edcdff8574d178ac1bfc81d2bcc2fad0d06` |
| Adapter provenance | `precice/openfoam-adapter`, OpenFOAM10 upstream commit `d53753b1c927b2413b02299c9da15725b3e772f0`; build006 patches `0001`, `0002`, `0004`, `0005` |
| OpenFOAM authority | Installed Foundation OpenFOAM 10 source under `/opt/openfoam10`; not a source checkout with an independently recoverable Git revision |
| Immutable failure | generation-2 checkpoint event 4; restore event 7 passed; second restore event 9 failed exact `oldPoints` identity. build007 subsequently reached the independent `V0 is not available` fatal. |

The prior `of10_rollback_state_equivalence_contract_v1.json` treatment of `oldPoints` as derived is not adequate under the now-frozen exact-identity requirement. This review does not alter that historical contract or its results.

## 1. Complete mesh-history dependency inventory

| State | OF10 owner / source behavior | Checkpoint class for this path | Restore requirement and next-solve dependency | Current build006 behavior |
|---|---|---|---|---|
| `Time::value`, `Time::timeIndex` | `Time`; adapter uses `Time::setTime(value,index)` | Exact persistent | Must precede motion/history restoration. Governs old-time and volume transitions. | Saved/restored. |
| `polyMesh::points_` | `polyMesh`; current geometry | Exact persistent | Must be checkpoint geometry before retry. `fvMesh` geometry caches are then rebuilt by supported mesh operations. | Saved as `meshPoints_`; restored through motion calls. |
| `polyMesh::oldPointsPtr_` | `polyMesh`; created by `polyMesh::movePoints()` when `curMotionTimeIndex_ != timeIndex` | Exact persistent | Supplies swept volumes to the same `movePoints()` call and therefore participates in mesh flux. It must not retain a rejected trial. | Saved as `oldMeshPoints_`, but not restored. |
| `polyMesh::curMotionTimeIndex_` | `polyMesh`; controls replacement of `oldPointsPtr_` | Exact persistent | Must be paired with `oldPointsPtr_`; otherwise a later `movePoints()` can preserve the wrong old geometry. | Not checkpointed/restored explicitly. |
| `polyMesh::moving_` and topology state | `polyMesh`; `moving_` becomes true for the run; topology is unchanged in this case | Conditional invariant / N/A | Preserve semantic consistency; no topology change is allowed by the frozen case. | Relied on implicitly. |
| `oldCellCentres` | demand-driven `polyMesh` history used only when configured/consumed | Conditional persistent | Inventory presence and values if the actual path allocates or reads it; otherwise explicitly N/A. | Not explicitly checkpointed. |
| `fvMesh::curTimeIndex_` | `fvMesh`; distinct from `polyMesh::curMotionTimeIndex_` | Exact persistent | Gates `storeOldVol(V())` in `fvMesh::movePoints()`. A wrong value can suppress V0 creation/update. | Not checkpointed/restored explicitly. |
| Current `V` and geometric caches | `fvMesh` demand-driven geometry | Legal derived state | May be rebuilt from restored current points by normal OF10 geometry update, but must match before next solve. | Rebuilt incidentally by movement calls. |
| `V0`, `V00` | private `fvMesh` volume-history pointers | Conditional exact persistent | If allocated or required by the active ddt scheme, preserve existence and values. `V0()` fatals when its pointer is absent. `V00()` derives only after `V0` exists. | Adapter's volume checkpoint code is disabled for non-subcycling and does not manage OF10 private lifecycle. |
| `meshPhi` / `fvMesh::phiPtr_` | private `fvMesh` mesh-motion flux field | Existence marker plus exact payload/history when present | A checkpoint-absent `meshPhi` may be legitimately created by the normal next motion; checkpoint-present `meshPhi` and relevant old times must be restored exactly. | Registered-field copies only once it exists; reload also calls `mesh_.phi()` if found. |
| Flow `phi` | registered flux field | Exact persistent plus required old times | Used by pressure/flux correction; separate from `meshPhi`. | Registered field checkpoint. |
| `U`, `p`, optional `Uf` | registered flow fields | Exact persistent plus relevant old times | Each next tentative solve consumes its value and applicable history. Lazy creation is acceptable only when deterministic next-solve equivalence is demonstrated. | Type-based field copies and up to observed old-time levels. |
| `pointDisplacement`, `cellDisplacement`, motion-solver reference state such as `points0` if registered/used | motion solver / registered fields | Exact persistent when read by the next motion solve | Must be inventoried from the actual dynamic-mesh configuration; neither total nor incremental semantics may be changed. | Field-copy path covers registered compatible fields, but does not replace mesh internal history. |

The decisive dependency is that `fvMesh::movePoints()` performs three coupled actions: it conditionally stores `V` into `V0/V00`, creates or updates `meshPhi`, then delegates to `polyMesh::movePoints()` for old/current-point swept volumes. `polyMesh::resetMotion()` touches only the latter layer. It cannot restore `fvMesh::curTimeIndex_` or volume history.

## 2. Source-level explanation of build006 and build007

### build006

The adapter checkpoint captures `meshPoints_ = mesh_.points()` and `oldMeshPoints_ = mesh_.oldPoints()`. On reload it performs, after restoring `Time`:

```text
reloadCheckpointTime()
  -> fvMesh::move()
       -> mover_->update()
            -> motion solver -> fvMesh::movePoints(trial-derived points)
  -> fvMesh::movePoints(meshPoints_)
  -> restore copied mesh fields
```

At the first move after the time rollback, `polyMesh::movePoints()` observes a new motion time index and writes the rejected trial geometry into `oldPointsPtr_`. The second `movePoints(meshPoints_)` call shares that restored `timeIndex`; it changes current points but does not replace `oldPointsPtr_`. Thus the current mesh returns to checkpoint points while `oldPoints` remains the rejected trial geometry. This exactly explains generation-2 event 9: its old-points fingerprint `5e2653f775fb87f0` equals the preceding trial mesh fingerprint, not the checkpoint fingerprint `ed1aa23b4b22b94a`.

### build007

Rejected patch `0006-of10-oldpoints-checkpoint-restore.patch` changed reload to:

```text
fvMesh::setPoints(oldMeshPoints_)
polyMesh::resetMotion()
fvMesh::movePoints(meshPoints_)
restore copied mesh fields
```

That establishes the checkpoint old/current point pair on the first restore, so the first oldPoints identity result passed. It is nevertheless not an atomic OF10 restore:

1. `setPoints()` clears geometry, including demand-driven `V0/V00` and `meshPhi` state through `fvMesh::clearGeom()`.
2. `resetMotion()` clears the polyMesh motion index/pointer only; it does not reset `fvMesh::curTimeIndex_`.
3. The normal `fvMesh::move()` lifecycle, which runs the mover and finally sets `curTimeIndex_ = time().timeIndex()`, was bypassed.
4. At the following tentative motion, `fvMesh::movePoints()` can see `curTimeIndex_` already equal to the restored time index. Its `curTimeIndex_ < time().timeIndex()` guard then skips `storeOldVol(V())` even though `setPoints()` has removed `V0`.
5. The subsequent `EulerDdtScheme<Vector>::fvmDdt()` path calls `V0()` and OF10 correctly raises `V0 is not available`.

This is a source-level lifecycle mismatch, not evidence that `V0` is intrinsically unnecessary in this non-subcycled case. The adapter's disabled V0/V00 *subcycling checkpoint* TODO and the solver's normal V0 requirement are separate concerns.

Confirmed: the call order and ownership above. Still requiring future fixture evidence: the exact runtime allocation/value envelope of `V0`, `V00`, `meshPhi` old-time, `oldCellCentres`, and every motion-solver reference field for the particular next solve.

## 3. Candidate recovery strategies

| Strategy | Source basis / required state | Normal OF10 motion semantics | Risk and maintenance | Assessment |
|---|---|---|---|---|
| **A. Adapter-only use of existing public OF10 APIs** | Would need to restore points, oldPoints, both motion indices, V0/V00, `meshPhi`, and geometry using only `setPoints`, `movePoints`, `move`, `resetMotion`, and registered field copies. | No public atomic API exposes/restores `polyMesh::oldPointsPtr_` plus `curMotionTimeIndex_`, nor `fvMesh::curTimeIndex_` plus V0/V00. build007 demonstrates that composing the available calls loses required lifecycle state. | Low implementation cost only if an unobserved supported API exists; current source audit found none. Repeating move/set/reset combinations risks fabricated swept volume or volume history. | **Not supported for the complete frozen contract.** Do not continue adapter-only call-order experiments. |
| **B. Pinned, versioned Foundation OF10 extension** | Add a narrowly scoped, owner-implemented mesh-history snapshot/restore interface inside OF10. It would restore `polyMesh` old-points/motion-index and `fvMesh` time-index, V0/V00 presence/value, meshPhi presence/value/history, plus necessary geometry invalidation/update as one transaction. Adapter calls only that public extension. | The extension must restore state without inventing a motion and leave the next real `fvMesh::move()` / `movePoints()` to build the next swept-volume transition normally. | Requires a separately reproducible OF10 build, ABI boundary audit, and regression maintenance. It touches OF10-owned private state only from OF10-owned code, rather than from adapter hacks. | **Technically viable design candidate; preferred only after explicit authorization to maintain a pinned OF10 extension.** |
| **C. Adopt an already-qualified compatible OF10/adapter stack** | A candidate must document native atomic checkpoint support for this exact mesh-history set and be built/qualified reproducibly. | Must preserve equivalent moving-mesh and preCICE semantics. | Highest migration and baseline-comparability cost. No such proven combination was identified in the frozen local evidence. | **Fallback, not currently selectable.** External candidate discovery and independent qualification are prerequisites. |

### Recommendation

There is no supported minimum recovery path in the current unmodified Foundation OF10 public API for the required complete state. Recommend authorizing a separate **implementation design task for Strategy B**, limited to a tiny OF10-owned public checkpoint object/API and its unit tests. This is not authorization to implement it now, and it is not authorization for a formal FSI retry. Strategy C should be considered only if the project does not accept an OF10 maintenance fork.

## 4. Atomic mesh-history restore contract (draft)

For checkpoint generation `g`, restore is valid only if it restores one coherent transaction before a retry receives new motion input.

### Exact persistent state

1. `Time` value and `timeIndex`.
2. Current mesh points; `oldPoints` payload and existence; `curMotionTimeIndex_`; applicable old-cell-centre state.
3. `fvMesh::curTimeIndex_`.
4. V0/V00 allocation existence and numeric content whenever allocated; absence is also an explicit state.
5. `meshPhi` allocation existence and, when present, current values and applicable old-time levels.
6. `U`, `p`, `phi`, optional `Uf`, point/cell displacement and every actual next-solve field/history, including their relevant old-time values.

### Legal derived state

Geometric caches (`V`, centres, face centres/areas and interpolation caches) may be invalidated and deterministically rebuilt only from the restored persistent state through OF10-owned lifecycle calls. A derived object may not carry trial data, change object ownership, or alter the next-solve result. The rebuild must be verified by same-input retry, not merely by presence or hash.

### Not applicable only with direct proof

Topology-map history is N/A only while topology is unchanged. `V00`, `oldCellCentres`, `Uf`, or meshPhi old-time are N/A only if the active case and next-solve path prove they are neither allocated nor consumed. No missing field is automatically a pass.

### Contract invariants

- A generation can be restored two or more times.
- Restore returns all exact persistent state to generation `g` before new trial input.
- Trial A cannot affect trial B; trial B starts from `g`, not trial A.
- Identical input after restore produces identical field, force, mesh, time, and history results under the frozen numerical identity rule.
- Different input produces its own geometry/solution without residual data from an earlier trial.
- Only the final converged iteration advances physical time and commits state once.

## 5. Pre-frozen next minimal verification plan (not executed)

This plan is conditional on later approval of Strategy B implementation. It is deliberately not a formal ANCF–CFD run.

1. **One OF10-owned lifecycle harness invocation.** Use the actual Foundation OF10 dynamic-mesh implementation and the same mesh-motion configuration. At OF time 0.100, checkpoint one mesh/history generation; apply total transverse trial A `+0.002 m`; restore; apply trial B `-0.002 m`; restore; apply B again. The harness must use normal adapter/preCICE motion input plumbing or an OF10-owned API test seam, never direct field writing as a qualification shortcut.
2. **One no-ANCF, real-preCICE prescribed-motion fixture invocation.** One physical window only, `dt=0.005 s`, OF time `0.100 -> 0.105 s`, fixed-point min/max `2/8`, with trials A, B, B as above. No altered mesh, PIMPLE, physics, relaxation, or subcycling. One failure ends the fixture; no automatic retry.
3. **One existing explicit prescribed-motion regression invocation**, only after both prior checks pass, at the same frozen one-step horizon. Compare to the established explicit fixture to show the OF10 extension does not change the non-rollback path.

At checkpoint, post-A restore, post-B restore, and final commit, record: current/old points full fingerprints and numeric differences; `curMotionTimeIndex_`, `curTimeIndex_`; V/V0/V00 allocation/value fingerprints; meshPhi allocation/value/old-time fingerprints; point/cell displacement; `U/p/phi/Uf` and relevant old times; Time value/index; centroid; mesh quality; and force decomposition after an actual solve.

Fail closed on missing required state, non-finite values, mismatch of any exact state, same-input nondeterminism, trial contamination, time double-commit, FPE, negative cells, or an explicit-regression deviation. The prior historical gate remains unchanged even if this later plan passes.

## 6. Risks, unresolved items, and decision

- The correct OF10 extension interface must be reviewed for object-registry and demand-driven ownership. It must not expose raw mutable private pointers to the adapter.
- The exact `oldCellCentres`, V00, meshPhi-old-time, `points0`, and field old-time inventory still requires a runtime lifecycle trace from the approved harness.
- A custom OF10 build adds ABI and patch-maintenance cost; every adapter build must record the OF10 extension commit and ABI identity.
- Build007 is not a repair candidate: it demonstrated why point restoration alone is insufficient and remains rejected.
- No conclusion here changes CFD physics, the coupling scheme, or any historical coupled result.

**Decision:** `IMPLEMENTATION_AUTHORIZATION = RECOMMENDED_CONDITIONAL`. The recommended next authorization is narrowly for a Strategy-B, OF10-owned atomic mesh-history checkpoint/restore API and the pre-frozen no-ANCF validation plan. `NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED`; `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.

## Git

No source or configuration was changed. This review records one documentation commit only:

`validation: review OF10 atomic mesh-history restore design`
