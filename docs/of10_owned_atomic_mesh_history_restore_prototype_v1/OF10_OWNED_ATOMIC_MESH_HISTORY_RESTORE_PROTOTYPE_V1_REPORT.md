# OF10-owned atomic mesh-history restore prototype V1

## Scope and disposition

This is a controlled prototype only. `/opt/openfoam10`, adapter build006 (`6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`), rejected build007 (`ec5fe81595c5a94a1436d8e907a02af828236b4d96d968c291f5052afc37e8fe`), the frozen worker, and every historical runtime were not modified.

The prototype stopped before adapter compilation. Its original first blocker was `ADAPTER_PATCH_SERIALIZATION_INVALID`: patch `0002-adapter-use-of10-owned-mesh-history-checkpoint.patch` was rejected by `patch` as malformed at line 8. The approved one-time serialization correction fixed the hunk-count/blank-context defect, but a clean build006 snapshot still rejected all four hunks under `patch --dry-run --fuzz=0`; `git apply --check` independently reported unmatched source context. Therefore no exact source-applicable patch has been established. Raw evidence is retained in `results/of10_owned_atomic_mesh_history_restore_prototype_v1/adapter_patch_application_failure.txt`. No adapter build, lifecycle harness, preCICE prescribed-motion fixture, explicit regression, formal ANCF--CFD run, or longer run was started.

The subsequent real-baseline audit resolved the source-context issue. The
actual build006 source chain is upstream `d53753b1c927b2413b02299c9da15725b3e772f0`
plus local patches `0001/0002/0004/0005`; production manifest and file hashes
were used, not an assumed clean upstream tree. A unified diff generated from
that source passes both `git apply --check` and `patch --dry-run --fuzz=0`.
However, its semantic review found that `reloadMeshPoints()` would invoke
`restoreMeshHistory()` and then the pre-existing `readMeshCheckpoint()` branch,
which restores meshPhi a second time. The original requested integration patch
does not specify how to reconcile that legacy meshPhi contract. Because a
removal or reconciliation would exceed pure patch-format repair, the work
stopped before adapter compilation and every runtime validation remains
unstarted.

## Independent OF10 implementation

An isolated copy was created under `/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/openfoam10`. It is Foundation OpenFOAM 10 (`linux64GccDPInt32Opt`, GCC 11.4.0), with the original `/opt/openfoam10` untouched.

Patch `0001-of10-owned-mesh-history-checkpoint.patch` adds the owner-managed `Foam::meshHistoryCheckpoint` type in the independent OF10 tree. `polyMesh` and `fvMesh` explicitly friend that type; the adapter is intended to see only `fvMesh::checkpointMeshHistory()` and `fvMesh::restoreMeshHistory()`. The snapshot stores current points, `oldPoints`, old cell centres when present, the two motion-time indices, `V0`/`V00` existence and values, and `meshPhi` plus up to two old-time levels. It fails closed for topology changes and unsupported meshPhi history depth. It does not use a private-state adapter bypass, layout cast, fabricated motion, or forced meshPhi initialization.

This is an implementation result, not a lifecycle qualification: the adapter could not be built to exercise the public API.

## Isolated build evidence

The following artifacts were rebuilt in the isolated prefix with no compiler or linker diagnostic in their build logs:

| artifact | SHA256 |
| --- | --- |
| libOpenFOAM.so | a34df8ad17f8250071c697d150e593563f2152c194b87fdb906b7a6493f37cde |
| libfiniteVolume.so | 50c251483d65cbf1f617990e39e12a9fbed1434ac419d8d2996ec1d3d5ba8a6e |
| libfvMotionSolvers.so | 921a49dbe05da5962aa43a82bb4e6b09185eaa6128b0defbf2dda73ca86ef6ca |
| libfvMeshMovers.so | e66b5f6d67d492bdd9f02187a71586198d5e32027fc8034ac7dc2e38c93712f2 |
| pimpleFoam | deebe14e05e1342c984db377c11979553a1fe44296ae0b6406501cac45b2288e |

`prototype_env.sh` pins `LD_LIBRARY_PATH` to this prefix before system MPI and preCICE locations, excluding both `/opt/openfoam10` and the legacy user OF10 library path. Under that environment, `ldd -r pimpleFoam` resolved `libfiniteVolume.so` and `libOpenFOAM.so` from the independent prefix and reported no unresolved symbols. This is only a partial ABI-closure check: without a prototype adapter, its full runtime dependency closure cannot be verified.

## Frozen validation sequence

All three authorized validations are `NOT_RUN`: OF10-owned lifecycle harness, one-window no-ANCF prescribed-motion preCICE fixture, and explicit prescribed-motion one-step regression. There is no evidence yet for oldPoints/V0/V00/meshPhi runtime restoration, same- or different-input isolation, next-solve equivalence, force, mesh quality, or formal coupling readiness.

## Decision

`OF10_OWNED_PROTOTYPE_BUILD = PARTIAL_PASS` (OF10 components only).

`ADAPTER_INTEGRATION = FAIL` (`MESH_PHI_DOUBLE_RESTORE_SEMANTICS_UNRESOLVED`).

`OF10_OWNED_LIFECYCLE_HARNESS = NOT_RUN`.

`PRESCRIBED_MOTION_FIXTURE = NOT_RUN`.

`EXPLICIT_ONE_STEP_REGRESSION = NOT_RUN`.

`NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED`.

`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.

## 2026-09-08 meshPhi single-owner integration update

This update supersedes the earlier `MESH_PHI_DOUBLE_RESTORE_SEMANTICS_UNRESOLVED`
integration disposition, but does not alter any historical runtime or gate.

The real build006 `Adapter.C` call graph was audited in full.  `writeCheckpoint()`
stores Time, calls `storeMeshPoints()`, then copies generic registered fields.
The legacy mesh-specific list contains only `meshPhi`.  `readCheckpoint()`
restores Time, calls `reloadMeshPoints()`, then restores generic fields.
Consequently, legacy `reloadMeshPoints()` could move points and restore a
specialized meshPhi copy after an OF10 snapshot restore; a pre-existing
meshPhi could additionally enter the generic `surfaceScalarField` list.  These
were two separate duplicate-owner paths.

The regenerated adapter patch is a unified diff made from the verified
build006 source.  It captures `fvMesh::checkpointMeshHistory()` once,
restores it once after Time restoration, removes all calls to legacy mesh
checkpoint write/read and mesh movement from that path, and excludes only
`meshPhi` from generic `surfaceScalarField` checkpoint setup.  Adapter-owned
U/p/fluid phi/Uf, displacement fields, Time, and all other regular field
histories are unchanged.  The legacy mesh functions remain in source but are
not called.  No adapter operation creates, deletes, or restores a runtime
meshPhi registry object.  The OF10-owned snapshot is the sole restore owner
for points/oldPoints, motion indices, V0/V00, meshPhi, and meshPhi old times.

The patch passed both strict gates in independent clean copies of the actual
build006 tree: `git apply --check --whitespace=error` and
`patch --dry-run --fuzz=0`.  Applying without fuzz produced the exact same
diff.  The single successful isolated adapter build is:

| artifact | SHA256 |
| --- | --- |
| `libpreciceAdapterFunctionObject.so` | `3312ef8311ec5069844d7114bac4a4618427ba4170fcadc65a19c254c3820dc8` |

`ldd -r` reports no unresolved symbols.  Adapter, `libOpenFOAM`,
`libfiniteVolume`, `libfvMotionSolvers`, and `libfvMeshMovers` resolve from
the independent `of10_owned_atomic_mesh_history_restore_prototype_v1`
prefix; `libprecice.so.3` is the pinned system preCICE dependency.  Neither
`/opt/openfoam10` nor build006/007 is in that closure.  An earlier build
directory stopped before compilation because the wrapper sourced OF10 bashrc
under `nounset`; its wrapper-only correction disables `nounset` while sourcing
the unmodified bashrc.  It did not alter adapter or OF10 runtime semantics.

The first authorized lifecycle-harness validation then fail-closed during
harness compilation, before any executable, CFD solve, preCICE participant,
or ANCF process started:

```text
fatal error: dynamicFvMesh.H: No such file or directory
```

The harness Make/options omitted OF10's dynamic-mesh header directory.  Under
the frozen sequence this is the unique first blocker:
`OF10_OWNED_LIFECYCLE_HARNESS_BUILD_FAILURE`.  No include-path repair,
rebuild, harness execution, prescribed-motion fixture, or explicit one-step
regression was attempted after it.

Current statuses:

- `ADAPTER_INTEGRATION = PASS`
- `OF10_OWNED_LIFECYCLE_HARNESS = FAIL`
- `PRESCRIBED_MOTION_FIXTURE = NOT_RUN`
- `EXPLICIT_ONE_STEP_REGRESSION = NOT_RUN`
- `NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED`
- `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`

## 2026-09-09 final authoritative update: copy mechanism not reproduced

The preceding localization describes the runtime observation accurately, but
the no-CFD numerical probe above supersedes its tentative operator-level
interpretation.  With the actual fixture_005 checkpoint (`0.100`) and nonzero
post-solve (`0.105`) fields, the exact `pointVectorField` copy construction,
forced `==`, ordinary `=`, and `reset` mechanisms are all component-wise
identical for internal values and every value-backed actual patch.  The
runtime failure is therefore an unresolved adapter lifecycle condition, not a
proven field-copy operator defect.  No production adapter patch is authorized
by this evidence.

Current authoritative statuses:

- `POINT_DISPLACEMENT_ROLLBACK_IDENTITY_FAILURE: ADAPTER_LIFECYCLE_CONDITION_UNRESOLVED`
- `REAL_PRECICE_JOINT_FIXTURE = FAIL`
- `EXPLICIT_ONE_STEP_REGRESSION = NOT_RUN`
- `NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED`
- `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`

## 2026-09-09 no-CFD pointVectorField copy semantics test

The earlier runtime trace localized the first observed mutation to the generic
adapter point-vector copy assignment.  It did **not**, by itself, prove that
Foundation OF10 `GeometricField::operator==` is defective.  A fresh no-CFD
probe was therefore compiled in the independent ABI prefix from the actual
build005 adapter source contract and OF10 headers.  It reads, but never writes,
the immutable fixture_005 case field and never loads preCICE, an adapter, or a
CFD solver.

| item | value |
| --- | --- |
| executable | `pointDisplacementFieldCopyProbe` |
| SHA-256 | `0d8b89596eefded26b1fe24f0f8da12f19091fedf9199df314ec32eb46f8e17d` |
| ABI closure | independent `libOpenFOAM`, `libfiniteVolume`, and `libmeshTools`; `ldd -r` has no unresolved symbols |
| inputs | fixture_005 actual `pointDisplacement` at both checkpoint `0.100` and nonzero final state `0.105` |
| methods | copy construction, `operator==`, `operator=`, `reset`, and forced/reset restore from a deliberately modified local copy |

For both time layers the internal field has 16,524 vectors and all tested
methods produce `max_abs=0`, `L2=0` against the untouched live field.  Actual
case patch types were read as `empty`, `symmetryPlane`, and `fixedValue`;
the value-backed `outlet` (122), `inlet` (122), and `cylinder` (80) patches
also have zero component-wise difference for every tested method.  The fields
have zero old-time levels at these read-only layers; the probe reports that
fact rather than fabricating one.

This falsifies the proposed mechanism that the ordinary standalone
`pointVectorField` `operator==` call intrinsically corrupts the copy.  The
runtime phenomenon depends on an unobserved adapter/checkpoint-lifecycle
condition not reproduced by the exact field operation.  Consequently there
is no proven safe production copy mechanism to substitute, and no adapter
source was modified.  In particular, replacing `==` with `=` is unsupported:
OF10 uses distinct forced and constraint-preserving point-boundary assignment
semantics, and this probe shows both are numerically correct in isolation.

No post-fix fixture or explicit regression was run.  The first blocker is
therefore refined, not cleared:

`POINT_DISPLACEMENT_ROLLBACK_IDENTITY_FAILURE: ADAPTER_LIFECYCLE_CONDITION_UNRESOLVED`.

The legacy runtime remains immutable and both formal gates remain
`NOT_AUTHORIZED`.

## 2026-09-08 lifecycle-harness build-configuration audit

The approved Make/options audit was completed against the isolated Foundation
OF10 source tree and ABI prefix.  The first compiler message named
`dynamicFvMesh.H`, but source inspection establishes that this is not an
include-directory omission: the independent OF10 tree contains neither that
header nor a `dynamicFvMesh` class.  Foundation OF10 in this prefix uses the
`fvMeshMover` / `fvMesh::move()` dynamic-motion path instead.  The existing
harness is therefore written against an incompatible, older dynamic-mesh API.

Adding an include directory or a linker library cannot make this source
compile.  Correcting it would require replacing its construction and motion
calls with the actual OF10 `fvMeshMover` lifecycle, which changes the harness
test implementation rather than its build configuration.  That exceeds the
authorized build-only correction, so no Make/options change was made, no
harness rebuild was attempted, and no validation runtime was launched.

The unique blocker is updated to:

`OF10_OWNED_LIFECYCLE_HARNESS_API_MISMATCH`.

The adapter build005 identity and its independent ABI closure remain valid;
this blocker concerns only the unexecuted lifecycle harness.  The prescribed
motion fixture and explicit one-step regression remain `NOT_RUN`.

## 2026-09-08 current-API semantic-equivalence audit

The approved Foundation OF10 API review confirmed the correct runtime chain:
`pimpleFoam` advances Time, then calls `fvMesh::move()`;
`fvMesh::move()` invokes its configured `fvMeshMover::update()`;
the configured `fvMeshMovers::motionSolver::update()` obtains its
`motionSolver::newPoints()` and calls `fvMesh::movePoints()`.  This is the
current real-mover replacement for the obsolete `dynamicFvMesh` API.

However, the standalone lifecycle harness has no lawful source for the frozen
nonzero A/B input.  In the production path, the adapter receives displacement
from preCICE and writes `pointDisplacement`; the mover then consumes that
field.  A harness that bypasses preCICE would have to either directly write
`pointDisplacement` or pass constructed points to `movePoints()`.  Both are
explicitly prohibited because they bypass the prescribed normal input path.

Consequently, changing only the harness construction from `dynamicFvMesh` to
`fvMesh` would not establish semantic equivalence to the frozen A -> restore
-> B -> restore -> B test.  Correctly refactoring it would require either a
preCICE-backed harness or an explicitly approved OF10/adapter input seam,
which is a test-design change rather than the approved API substitution.  No
harness code or Make/options was changed in this continuation, and no run was
launched.

The first blocker remains `OF10_OWNED_LIFECYCLE_HARNESS_API_MISMATCH`, now
with a source-level semantic cause rather than an include-path classification.
All subsequent frozen validations remain `NOT_RUN`; both next formal gates
remain `NOT_AUTHORIZED`.

This malformed-patch recommendation is historical only.  The serialization and
baseline-context issue was subsequently resolved for build005; it is not the
current blocker and must not be used to justify another integration run.

## 2026-09-08 real preCICE joint-fixture result

The obsolete standalone lifecycle harness remains a historical
`OF10_OWNED_LIFECYCLE_HARNESS_API_MISMATCH = FAIL`.  It was not repaired or
reclassified.  Under the subsequently authorized replacement design, one
real, no-ANCF, preCICE prescribed-motion fixture was run through the normal
adapter and OF10 mover path, using adapter build005 and the isolated ABI
prefix.  This is the only physical invocation of this replacement fixture:

| item | value |
| --- | --- |
| runtime | `runtime/of10_owned_atomic_mesh_history_restore_prototype_v1_precice_fixture_002` |
| time | OF `0.100 -> 0.105 s`; one physical window; `dt=0.005 s` |
| fixed-point contract | 3 trials, 2 restores, min/max 2/8, no acceleration |
| adapter | `adapter_build_005/lib/libpreciceAdapterFunctionObject.so` |
| adapter SHA-256 | `3312ef8311ec5069844d7114bac4a4618427ba4170fcadc65a19c254c3820dc8` |
| participant / fluid return codes | `0 / 0` |

The trace contains one `CHECKPOINT_WRITE`, two
`PRE_ROLLBACK_TRIAL`/`POST_ROLLBACK_BEFORE_NEXT_INPUT` pairs, and one
`FINAL_COMMIT`.  The structure-side participant made exactly one physical
commit at coupling time `0.005 s`.  The fluid committed once at OF `0.105 s`.
The prescribed input entered the normal adapter path: the first trial
centroid was `y=0.1778611381392648 m` versus the checkpoint
`y=0.17720998354325726 m`; after each restore it returned exactly to the
checkpoint centroid; and the final `-0.002 m` input committed a distinct
centroid of `y=0.17655882894725095 m`.  The two pre-rollback trials have
identical U/p/phi/Uf, points, oldPoints, meshPhi and force-generating state
fingerprints, which is evidence for same-input deterministic replay.  It is
not a substitute for a successful full different-input-after-restore proof:
the preCICE time-layer trace supplied the same positive sample to both
pre-rollback trials, while the different negative sample was used only by the
final committed trial.

The owner-managed mesh result is positive but partial: checkpoint-to-restore
identity holds for U, p, phi, Uf current values, cellDisplacement, full mesh
points, and oldPoints.  `meshPhi` is absent at the checkpoint and both
post-restore events, then deterministically exists in the equal trial states;
it is therefore a lawful derived demand-driven field in this generation, not
a stale registry object.  U/Uf acquire one old-time level after the first
trial; the restored old-time values equal their checkpoint current values,
which is classified as `DERIVED_LAZY_RECONSTRUCTED_NUMERICALLY_EQUIVALENT`,
not as exact history-inventory identity.  V0/V00 remain
`NOT_APPLICABLE_NON_SUBCYCLED`; no V0 fatal occurred in the real next solves.
The private motion indices are not directly fingerprinted by build005, so
their exact values are `NOT_DIRECTLY_OBSERVABLE`; time/timeIndex, geometry
restore, and successful repeat solve provide only behavioral evidence.

### First new blocker: pointDisplacement restoration

The first post-rollback event is nevertheless a hard failure of the frozen
ordinary-field contract.  The checkpoint `pointDisplacement` fingerprint is
`b92b3b2e4e49feda`; each post-restore event records
`1631ccd0062a8ae2`.  This is not a meshPhi ownership issue and must not be
reclassified as a PASS merely because the mesh points are restored and the
next same-input solve is repeatable.  The source shows that the adapter
intends to copy registered `pointVectorField`s in its generic checkpoint
lists, but the present trace does not establish whether `pointDisplacement`
was omitted from that list or changed during a later restore operation.
Accordingly the exact implementation cause remains unproven, while the
runtime fact is conclusive:

`POINT_DISPLACEMENT_ROLLBACK_IDENTITY_FAILURE`.

No patch or repeat run was attempted.  The subsequent explicit prescribed
motion one-step regression is therefore `NOT_RUN`, as required by the
stop-on-first-runtime-semantic-failure rule.  The final committed force,
which is diagnostic-only and not a formal FSI result, was pressure
`(602.6026006673, 61261.08075349) N`, viscous
`(704.7704353911, 702.9772731850) N`, total
`(1307.3730360584, 61964.0580266706) N` in `(Fx,Fy)`.

The final fluid trial completed without FPE.  Its terminal Ux/Uy/p residuals
were `3.6055e-09`, `3.8821e-09`, and `6.6178e-09`; maximum fluid Courant was
`0.3503035`.  A post-run full `checkMesh` invocation could not be retained
because the isolated utility environment did not resolve its mandatory
OpenFOAM runtime configuration.  Consequently a standalone full-checkMesh
negative-cell result is `NOT_EVALUABLE`; it is not asserted as a PASS.

Current authoritative statuses are:

- `ADAPTER_INTEGRATION = PASS` (build005 only)
- `OF10_OWNED_LIFECYCLE_HARNESS = FAIL` (historical API mismatch)
- `REAL_PRECICE_JOINT_FIXTURE = FAIL` (`POINT_DISPLACEMENT_ROLLBACK_IDENTITY_FAILURE`)
- `EXPLICIT_ONE_STEP_REGRESSION = NOT_RUN`
- `NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED`
- `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`

## 2026-09-09 pointDisplacement copy-assignment localization

The original build005 runtime and its failure remain immutable.  A separate,
diagnostic-only adapter build was used solely to locate the existing failure:

| item | value |
| --- | --- |
| diagnostic adapter | `adapter_diagnostic_point_displacement_003/lib/libpreciceAdapterFunctionObject.so` |
| SHA-256 | `fef5f8bc5f384907921e266219114e058a69df7764dc5d271fdbccb6056190a9` |
| ABI check | `ldd -r` has no unresolved symbol or missing library |
| immutable diagnostic runtime | `runtime/of10_owned_atomic_mesh_history_restore_prototype_v1_precice_fixture_005` |
| execution | one `0.100 -> 0.105 s` no-ANCF preCICE fixture; 3 trials, 2 restores, one final commit |

The source and runtime evidence now establish all of the following:

1. `pointDisplacement` is in the generic `pointVectorField` checkpoint list.
2. Immediately before the generic point-vector checkpoint assignment, both
   the live field and its copy fingerprint are `b92b3b2e4e49feda`.
3. The sole existing assignment
   `*pointVectorFieldCopies_[i] == *pointVectorFields_[i]` changes the copy
   immediately to `1631ccd0062a8ae2`, while the live field remains
   `b92b3b2e4e49feda`.
4. Owner mesh-history restore leaves that bad copy untouched; generic restore
   then transfers it to the live `pointDisplacement` field.  No new preCICE
   sample is read until the later `POST_NEXT_COUPLING_INPUT` event.

Thus registration, the OF10-owned mesh snapshot, and input timing are not the
cause.  The first causally observed mutation is the adapter's generic
point-vector copy assignment.  The diagnostic patch was regenerated from a
real source diff and, after correcting its path serialization, passes both
`git apply --check --whitespace=error` and `patch --dry-run --fuzz=0` on the
verified source snapshot.

Foundation OF10 source also shows that this is not safely repairable by a
blind `==` to `=` substitution: `GeometricField::operator==` is a forced
boundary-value assignment, while ordinary `operator=` delegates normal point
patch assignment, which for a `valuePointPatchField` may retain its patch
internal value rather than copy the source boundary value.  The present trace
does not yet provide a numeric, per-component explanation for why the forced
assignment changes the copy internal state.  Therefore an exact safe
production repair is **not proven**.  No production adapter patch, no fresh
post-fix validation fixture, and no explicit regression were run.

### Current authoritative update

The no-CFD numerical probe supersedes the tentative operator-level
interpretation above: the exact `pointVectorField` copy construction, forced
`==`, ordinary `=`, and `reset` mechanisms are component-wise identical at
fixture_005 `0.100` and `0.105`.  The runtime failure is consequently an
unresolved adapter lifecycle condition, not a proven field-copy operator
defect.  No production adapter patch was generated or run.

- `POINT_DISPLACEMENT_ROLLBACK_IDENTITY_FAILURE: ADAPTER_LIFECYCLE_CONDITION_UNRESOLVED`
- `REAL_PRECICE_JOINT_FIXTURE = FAIL`
- `EXPLICIT_ONE_STEP_REGRESSION = NOT_RUN`
- `NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED`
- `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`
