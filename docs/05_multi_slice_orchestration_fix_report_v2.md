# Stage 4B-v2 multi-slice orchestration fix report

## Status and scope

**Status: partially_completed.** The dispatcher and checkpoint layer have been
migrated to the frozen 0.2.1 A-module implementation. Mock two-/five-slice
barriers, A-to-B cross-validation, staged checkpoint transactions, recovery,
restart validation, the parameterized case template, and the static
`motionScale` restart smoke are complete. A real two-slice run was attempted
with two OpenFOAM-10 processes and the production ANCF runner wrapper, but the
run was fail-closed after the first committed step because the dynamic case
reached CFL 11.633799 and then could not produce the second-step force. No
two-step free CFD--ANCF claim is made.

Stage-three evidence and the formal public contract were not modified.

## Protocol compatibility

The only schema/hash source used by the new B implementation is
`src/coupling/multi_slice_mapping/mapping.py`:

```text
schema_version          = 0.2.1
slice_manifest_sha256   = ffbf9af8cfe8d65d90762fe088c89e4f427c0eb6a010a20741cee788e6437a5d
config_sha256           = 2c8b815b2bf43cd8581e5eeef604a456d7cff8ca77fb0f4ae08978ec28efd9aa
```

The dispatcher now writes the complete static manifest and a separate runtime
config containing only the manifest digest. `MotionRecord`, `LoadRecord`,
ready/consumed marker classes, canonical JSON, SHA-256, load conversion and
`map_integrated_slice_forces` are imported from A. The old B-side 0.2.0 field,
manifest and hash implementation has been removed from the execution path.

## State machine and barrier

The normal path is:

```text
INITIALIZED -> PREDICTED -> MOTION_PUBLISHED -> MOTION_CONSUMED
             -> CFD_ADVANCED -> LOADS_READY -> LOADS_CONSUMED
             -> STRUCTURE_CORRECTED -> CHECKPOINT_PREPARED -> COMMITTED
```

`FAILED` is terminal for a pre-commit transaction. If the committed manifest
has already been atomically published but in-memory structure finalization
fails, the state is `RECOVERY_REQUIRED`; it is never relabeled `FAILED`.
Recovery validates the committed manifest and all file hashes, restores every
slice and the ANCF checkpoint, and only then allows the next step. A second
commit for the same step is rejected.

Each global step performs the following barrier:

1. Predict the complete motion set and validate all A records.
2. Publish each immutable 0.2.1 motion CSV, then publish its ready marker.
3. Wait for every motion consumed marker.
4. Let every slice advance one CFD step.
5. Wait for every load ready marker, reread and validate every load payload.
6. Convert OpenFOAM force to integrated slice force exactly once and call the
   A-module H-transpose mapper.
7. Publish every load consumed marker.
8. Create staged ANCF correction, export staged q/qdot/qddot, prepare all CFD
   files and the ANCF checkpoint, then validate the prepared manifest.
9. Atomically publish the root committed manifest.
10. Call idempotent `finalize_committed`; only then enter `COMMITTED` and
    release the next step.

There is no old-load fallback. Missing, future, stale, duplicate, NaN/Inf,
hash-inconsistent or timeout data fails the complete transaction.

## Exchange and checkpoint layout

The exchange layout is:

```text
exchange/
  slice_manifest.json
  config.json
  transaction_log.jsonl
  slice_0000/{motion,load,consumed}/...
  slice_0001/{motion,load,consumed}/...
```

The checkpoint manager retains a prepared manifest below
`checkpoints/.pending/<checkpoint_id>/`; it is never restartable. The only
restartable artifact is `checkpoints/checkpoint_<checkpoint_id>.json` with
`status=committed`.

Each slice entry has separate `static_files` and `time_files` lists. The static
list records `0/motionScale`; the time list records `U`, `p`, `phi`, `Uf`,
`meshPhi`, `polyMesh/points`, and `uniform/time` under the actual OpenFOAM
time directory. Every entry records relative path, byte count and SHA-256.
`motionScale` is not copied into a later time directory.

## Atomic transaction semantics

The structure wrapper contract is:

```text
correct_all                 -> staged correction
export_staged_checkpoint    -> staged q/qdot/qddot and token
discard_staged              -> allowed only before manifest publication
finalize_committed          -> idempotent late in-memory finalization
load_checkpoint             -> committed restart restoration
```

The tests cover staged correction failure, staged export failure, CFD file
preparation failure, atomic manifest publication failure, post-publication
finalization failure, slice restore failure and structure restore failure.
Pre-commit failures leave no committed manifest and do not advance committed
structure state. Post-commit finalization failure retains the committed
manifest and requires recovery.

## Restart rules

Restart re-computes all hashes before invoking any adapter. It rejects status
other than `committed`, temporary/prepared manifests, changed slice count or
identity, changed configuration or manifest digest, changed dt, missing CFD or
ANCF fields, changed file bytes, invalid time directory, and non-finite or
inconsistent q/qdot/qddot. Successful restart resumes at `step+1` with the
previous committed slice forces and generalized force.

## Failure-injection coverage

The combined mock matrix covers missing/duplicate slice identity, missing
motion consumed, missing load ready, wrong time, wrong step, early step, wrong
coupling iteration, payload/config/manifest hash errors, NaN, Inf, timeout,
non-zero process exit, all eight required CFD checkpoint fields, missing ANCF
checkpoint/q/qdot/qddot, structure correction failure, staged correction and
staged export failure, CFD preparation failure, atomic publish failure,
post-commit finalization failure, slice/structure recovery failure, stale
fallback rejection, prepared/temp restart rejection, tampered restart, and
successful continuous restart.

The A-to-B test creates records and markers with the A production classes and
consumes them through the B protocol layer. A payload mutation after ready is
rejected by the B reader.

## Production ANCF adapter

`ProductionANCFAdapter` wraps the existing persistent ANCF runner without
modifying `structure_runners` or ANCF mechanics. It builds H with
`build_H_for_manifest`, calls A's H-transpose mapper, checks finite q state,
uses a pre-correction runner checkpoint as the pre-commit rollback snapshot,
and carries a checkpoint token through export/finalize/recovery.

The stage-three MATLAB worker currently returns motion and energy in JSON but
does not expose q/qdot/qddot. The wrapper therefore requires an explicit
`state_provider` for production operation; the real smoke obtains this view
from the runner's existing MATLAB checkpoint MAT file using SciPy. Sol should
decide whether q/qdot/qddot should become an official persistent-runner JSON
response in a future integration task.

## OpenFOAM results

The independent static restart smoke passed with OpenFOAM-10: one process,
restart from 0.0025 s to 0.005 s, return code 0, maximum CFL 0.16794536, and
`0/motionScale` SHA-256
`79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4`. This
provides evidence for the case-level static-file strategy only.

The real two-slice attempt used two independent cases, the formal 0.2.1
manifest/config, two OpenFOAM processes, and the production ANCF wrapper. One
global checkpoint at 0.0025 s was atomically committed and contains all
required CFD static/time fields and finite ANCF state. The next global step
was stopped: maximum CFL reached 11.633799, both OpenFOAM processes exited
non-zero after the motion bridge became stale, and no second global checkpoint
was accepted. This is a blocked safety result, not a completed two-step
closed-loop result.

The unchanged stage-three `ancfFileMotion` reader requires an explicit
materialized 0.1.0 motion view. The new smoke keeps that bridge explicit and
retains the 0.2.1 payload/marker/hash as the scheduler transaction. Sol must
confirm this bridge as an approved production integration boundary before any
future closed-loop claim.

## Interface requests to Sol

1. Decide whether the explicit 0.2.1-to-stage-three motion materializer is the
   sanctioned production bridge, including the mapping between global target
   time and the CFD reader's current time.
2. Decide how the persistent ANCF runner officially exports q/qdot/qddot and
   staged/finalized correction state; the wrapper currently uses an explicit
   state provider and MAT checkpoint snapshot.
3. Review the real smoke CFL failure and motion-bridge timing logs before any
   further heavy CFD attempt.

No public protocol, mapping implementation, stage-three runner, ANCF core,
stage-three case, or stage-three evidence was changed.

