# Orchestrator interface requests for Sol

This note is a request only. The public `docs/05_multi_slice_contract.md`,
stage-three online protocol, and production `ancfFileMotion` source were not
modified by this task.

## 1. Immutable Draft-1 to stage-three motion bridge

The new scheduler publishes immutable Draft-1 files named
`motion_stepXXXXXXXX_iterXXXX.csv` with `0.2.0` markers. The existing
stage-three `ancfFileMotion` library consumes a materialized `0.1.0`
`motion.csv` plus `motion_ready` view. Sol should decide whether the formal
integration owns a per-slice materializer or whether a future production
adapter accepts Draft-1 directly. The bridge must retain the original
payload hash and must not create an old-step fallback.

## 2. Transactional structure correction boundary

The scheduler assumes `correct_all` creates a staged state, while
`commit_corrected` is called only after the global manifest is atomically
committed and `discard_correction` is called on failure. The existing
persistent ANCF runner contract exposes `correct`/`save_checkpoint` but does
not state this late-commit boundary. Sol should define the production wrapper
or a snapshot/rollback rule before connecting it.

## 3. OpenFOAM checkpoint `motionScale`

The real two-case smoke wrote `U`, `p`, `phi`, `Uf`, `meshPhi`,
`polyMesh/points`, and `uniform/time` at `0.0025`, but did not write
`motionScale` into that time directory. The orchestrator rejects the global
checkpoint as required. Sol should decide how the production case writes and
hashes `motionScale`; this task intentionally did not copy the initial field
into a later time directory or otherwise fabricate evidence.

## 4. Formal contract ownership

Sol should create and freeze `docs/05_multi_slice_contract.md` after reviewing
the implementation's field order, marker names, path semantics, and
checkpoint relative-path resolution. No formal public contract file was
created or changed here.

