# CHECKPOINT_AWARE_STRUCTURE_PARTICIPANT_AND_ONE_WINDOW_IMPLICIT_QUALIFICATION_V1_REPORT

- Fresh runtime: `runtime/implicit_one_window_v1_run_001` (immutable).
- Scope: exactly one planned physical coupling window, `dt = 0.005 s`; no 0.05 s run was started.
- Result: `ONE_WINDOW_IMPLICIT_QUALIFICATION = FAIL`.

## Production checkpoint participant

The new versioned participant is [implicit_structure_participant.py](../../tools/checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1/implicit_structure_participant.py).  It follows the deployed preCICE 3.4 callback sequence: write a physical checkpoint when `requires_writing_checkpoint()` is true and restore it when `requires_reading_checkpoint()` is true.

Restorable state is the C++ adapter checkpoint (`q`, `qdot`, `qddot`, committed state and adapter integration state), Python prior slice force state, physical window/tau state, and window-local state.  Non-restorable state is explicitly limited to wire request ID, transaction/transport identity and evidence attempt identity.  These identities remain monotonic across restore.

The offline production regression passed: six restore/retry cycles had exact physical-state restoration, deterministic repeated response, no previous-force contamination, and twelve unique wire sequences.  The frozen explicit participant was not modified; its default launcher path remains unchanged (`EXPLICIT_PARTICIPANT_REGRESSION = PASS_BY_ISOLATION`).

## Actual one-window qualification

The runtime reached the following real implicit events:

1. Structure checkpoint write for physical window 1.
2. Trial-1 C++ prediction and correction, wire sequences 1 and 2.
3. preCICE requested a structure rollback; the recorded post-restore physical-state hash equals the checkpoint hash.
4. Trial-2 C++ prediction used a new wire sequence 3.

The fluid participant then exited before a valid fluid solve.  Its direct OpenFOAM error is:

```
keyword cellDisplacement is undefined in dictionary .../system/fvSolution/solvers
```

This is the unique first failing gate: `OPENFOAM_MESH_AUXILIARY_SOLVER_CONFIGURATION_MISSING`.

Consequently, no physical window committed; no valid CFD force, Quality V4 result, or final converged force exists.  The first C++ trial used zero force only because the fluid process had already failed; it is not hydrodynamic evidence.  Generalized Force V2 passed for that persisted zero-load attempt, but the whole one-window gate is not qualified.

## Required disposition

- Structure checkpoint write/read: observed; physical restore identity passed.
- Wire identity: monotonic and unique in the observed retry.
- OpenFOAM U/p/phi/Uf/meshPhi rollback: `NOT_EVALUABLE` (no successful fluid trial).
- Dynamic-mesh rollback / cumulative geometry check: `NOT_EVALUABLE` (same reason).
- Quality V4: `NOT_EVALUABLE`.
- Final force: `NOT_AVAILABLE`.
- No 0.05 s implicit diagnostic was launched.

## Minimal blocker and decision

The authoritative future-case generator must supply an actual `cellDisplacement` solver entry compatible with the OpenFOAM 10 `displacementLaplacian` path (not merely `cellDisplacementFinal`).  This fresh failure is retained and will not be rerun in this task.

`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.
