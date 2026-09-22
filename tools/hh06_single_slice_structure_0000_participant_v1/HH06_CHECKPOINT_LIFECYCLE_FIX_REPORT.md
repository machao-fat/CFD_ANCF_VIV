# HH06_CHECKPOINT_LIFECYCLE_FIX

## Scope and execution boundary

This change fixes the physical-checkpoint lifetime used by the HH06
`Structure_0000` orchestration path.  No OpenFOAM case, preCICE XML, ANCF
kernel, worker binary, SHM1 protocol, or physical contract was changed.  No
OpenFOAM, preCICE, or ANCF runtime was started, and no CFD time directory was
created.

## Root cause

`GenericStructuralCoordinator.rollback()` restored the backend snapshot and
then set its active `_checkpoint` to `None`.  In a preCICE parallel-implicit
window, a rejected iteration may be followed by another rejection before the
window is accepted.  The second rollback therefore raised
`CheckpointError: no active checkpoint` even though the same physical window
checkpoint was still required.

## Minimal implementation

Modified source:

- `src/coupling/arbitrary_n_live_orchestration_v1/coordinator.py`

`rollback()` now restores the physical/solver snapshot and clears only the
per-attempt gather, iteration, tentative-advance, and motion state.  It keeps
the current `CouplingCheckpoint` active.  `commit()` remains the sole
operation that clears `_checkpoint` after an accepted window.

No HH06 wrapper modification was required: the wrapper already takes the
checkpoint at the beginning of a window and invokes coordinator rollback on a
preCICE retry.

## State ownership after the fix

| State | Checkpoint snapshot | Rollback | Commit |
|---|---:|---:|---:|
| `q`, `qdot`, `qddot` | saved | restored exactly | retained as accepted state |
| tentative solver/backend state | saved | restored | finalized by backend |
| gathered force / iteration / tentative flag | coordinator transient | cleared for retry | cleared |
| `global_step`, physical time/window identity | represented by request/checkpoint | restored to window identity | advances on acceptance |
| `sequence`, `request_id`, `transaction_id` | not saved by production HH06 backend | never decremented | remain monotonic |
| active window checkpoint | retained | retained | cleared |

This preserves the existing transport-ID duplicate detection.  A retry gets a
new transport identity while replaying the same physical window.

## Offline regression tests

Added:

- `tests/hh06_checkpoint_lifecycle/test_checkpoint_lifecycle.py`

The test backend is deterministic and deliberately excludes transport IDs
from its physical snapshot.  It does not import preCICE or start a worker.

1. **Rollback once:** `q`, `qdot`, and `qddot` restore exactly; checkpoint
   remains active.
2. **Rollback twice in one window:** the same checkpoint is reused; transport
   sequence/request/transaction IDs are `1 -> 2` with no duplicate.
3. **Rollback -> retry -> commit:** the retry state is committed; checkpoint
   is cleared only after `commit()`; a later rollback is rejected.

Verification performed:

- Python syntax compilation: PASS
- HH06 checkpoint lifecycle tests: **3/3 PASS**
- Existing arbitrary-N/multi-slice orchestration tests: **7/7 PASS**
- Existing preCICE adapter/lifecycle tests: **14/14 PASS**

## Final status

`HH06_CHECKPOINT_LIFECYCLE_FIX = PASS`

The failed 50-window runtime evidence remains untouched.  The 50-window or
0.2-second HH06 run was **not** restarted by this task.
