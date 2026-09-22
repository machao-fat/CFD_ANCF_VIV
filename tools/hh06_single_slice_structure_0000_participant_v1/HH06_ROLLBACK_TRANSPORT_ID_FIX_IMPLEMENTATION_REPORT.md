# HH06 Rollback Transport-ID Fix Implementation Report

## Scope and execution boundary

Implementation authorized by the approved design
`HH06_ROLLBACK_TRANSPORT_ID_FIX_DESIGN = PASS`.

Only the Python `PersistentHH06KernelBackend` in
`tools/hh06_single_slice_structure_0000_participant_v1/structure_0000_participant.py`
was changed.  No ANCF kernel/source, worker binary, SHM1 protocol,
`kernel_protocol.py`, HH06 contract, preCICE XML, or CFD case was modified.

No OpenFOAM, preCICE, or ANCF physical runtime was started.  No physical
time directory was created.

## Root cause fixed

Before this patch, `attempted_advance_count` simultaneously generated:

```text
sequence
case_local_bridge_step
request_id
transaction_id
```

The backend checkpoint stored and restored that counter.  After a physical
rollback, the persistent C++ worker still retained its process-lifetime
sequence and seen-ID sets, while Python regenerated the same wire identities.
The worker correctly rejected the replay as a duplicate transport request.

The fix separates physical-window identity from session transport identity.
An implicit retry now uses a fresh wire sequence/request/transaction ID while
retaining the same `global_step`, `case_local_bridge_step`, time, and `dt`.

## Before/after state ownership

| State | Before | After |
|---|---|---|
| `q`, `qdot`, `qddot` | checkpointed/restored | checkpointed/restored |
| `_pending` tentative lifecycle | checkpoint field, restore behavior implicit | checkpointed/restored explicitly |
| `committed_advance_count` | checkpointed/restored | physical-window state; checkpointed/restored |
| `attempted_advance_count` | generated wire IDs and was restored | diagnostic monotonic attempt count; never checkpointed/restored |
| `sequence` | derived from restored attempt count | session-monotonic `_transport_sequence_counter`; never restored |
| `request_id` | derived from restored attempt count | session-monotonic `_transport_request_id_counter`; never restored |
| `transaction_id` | derived from restored attempt count | session-monotonic `_transport_transaction_id_counter`; never restored |
| `global_step` | committed count + 1 | physical window `committed_advance_count + 1` |
| `case_local_bridge_step` | transport attempt count | same physical window as `global_step`, including retry |
| C++ worker duplicate-ID sets | process-owned and never rolled back | unchanged; duplicate detection remains enabled |

## Implementation details

The backend now initializes independent transport counters for one worker
session.  Counters fail closed before reaching the wire-width limit; they are
never decremented or reset by `restore()`.

`snapshot()` contains only physical/tentative state:

```text
q, qdot, qddot, committed, pending
```

Legacy in-memory snapshots containing an `attempted` field remain readable,
but that field is deliberately ignored.  The next retry emits the identity
sequence:

```text
Trial A:  sequence=1, global_step=1, bridge_step=1, request_id=910001, transaction_id=1910001
Retry B:  sequence=2, global_step=1, bridge_step=1, request_id=910002, transaction_id=1910002
Next C:   sequence=3, global_step=2, bridge_step=2, request_id=910003, transaction_id=1910003
```

This preserves the C++ worker's duplicate-ID protection and its implicit-retry
lineage contract.

## Modified files

1. `CFD_ANCF_VIV/tools/hh06_single_slice_structure_0000_participant_v1/structure_0000_participant.py`
   - added session-monotonic transport counters;
   - made checkpoint/restore physical-only;
   - separated retry wire identity from physical-window identity;
   - added fail-closed counter exhaustion checks.

2. This report:
   `CFD_ANCF_VIV/tools/hh06_single_slice_structure_0000_participant_v1/HH06_ROLLBACK_TRANSPORT_ID_FIX_IMPLEMENTATION_REPORT.md`

No other source or runtime file was changed for this implementation.

The repository already contained an unrelated pre-existing working-tree
modification in `src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py`;
it was not opened or modified by this implementation.

Post-implementation SHA256 of the modified backend source:

```text
C5401DDF05C0C312B69F2C6DDE0C8CC130BCCE16753CDD0E5258CFBBE95D1C46
```

## Verification results

### Syntax

```text
python -m py_compile tools/hh06_single_slice_structure_0000_participant_v1/structure_0000_participant.py
PASS
```

### Targeted backend rollback/transport unit check

An offline fake-stream fixture exercised the production backend request
construction (without starting a worker):

- checkpoint contains no transport identity fields;
- restore leaves diagnostic and transport counters monotonic;
- retry receives fresh sequence/request/transaction IDs;
- retry retains `global_step=1` and `case_local_bridge_step=1`;
- post-commit request advances to physical window 2;
- all assertions passed.

```text
HH06_BACKEND_ROLLBACK_TRANSPORT_ID_FIX_UNIT=PASS
```

### Existing pure-Python backend/rollback-related tests

Command (run from `CFD_ANCF_VIV`, with `src` on `PYTHONPATH`):

```text
python -m unittest -v \
  tests.cpp_worker_confirm_v1.test_barrier \
  tests.cpp_worker_confirm_v1.test_lifecycle \
  tests.precice_ancf_adapter_v1.test_barrier_storage_faults \
  tests.precice_ancf_adapter_v1.test_mapping_protocol \
  tests.performance_optimization_v2.test_coordinator \
  tests.cpp_worker_persistent_ipc_v1.test_offline_contracts
```

Result:

```text
37 tests, 37 passed, 0 failed
```

The C++ worker process tests were not launched because this implementation
phase explicitly excludes worker/ANCF runtime qualification.  The Python
`pytest` executable is not installed in this environment; equivalent
`unittest` suites were used.

## Status

```text
HH06_ROLLBACK_TRANSPORT_ID_FIX_IMPLEMENTATION = PASS
NEXT_PHASE = HH06_OFFLINE_RUNTIME_QUALIFICATION (manual authorization required)
NO_OPENFOAM_RUN = true
NO_PRECICE_RUN = true
NO_ANCF_PHYSICAL_RUNTIME = true
```

The next requested offline runtime qualification has **not** been started.
