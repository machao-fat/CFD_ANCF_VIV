# HH06 rollback / transport-ID lifecycle audit

## Scope and gate

This is a read-only source audit.  No worker was started, no ANCF step was
advanced, no preCICE participant was initialized, no OpenFOAM process was
started, and no case file or protocol source was modified.

**Current gate remains:** `DO_NOT_PASS`

**Audited blocker:** `PRODUCTION_BACKEND_ROLLBACK_REUSES_TRANSPORT_IDS`

The audit follows the HH06 Structure_0000 wrapper, the generic structural
coordinator, the preCICE backend proxy, the Python persistent-IPC codec, and
the qualified C++ worker source.

## A. Physical state versus transport state

### Physical state

| object | fields | owner | physical meaning |
|---|---|---|---|
| ANCF state | `q`, `qdot`, `qddot` | `PersistentHH06KernelBackend` / C++ request input | structural position, velocity, acceleration |
| tentative lifecycle | `_pending` / `_pending_advance` | backend / coordinator | whether a trial structural state has not yet committed |
| coupling gather | `_gather`, `_iteration`, `_time_s`, `_last_request`, `_last_motion` | `GenericStructuralCoordinator` | current force window and tentative motion bookkeeping |
| committed physical window | `committed_advance_count`, coordinator `committed_step` | backend / coordinator | number of committed structural windows; used to derive `global_step` |
| checkpoint physical snapshot | q/qdot/qddot plus lifecycle counters | `CouplingCheckpoint.backend_state` | state to which a failed implicit trial is restored |

The C++ worker is request-state driven: each `KernelStepRequest` carries q,
qdot and qddot.  Its numerical state for a request is reconstructed from that
payload; the worker nevertheless retains transport/lineage state in its
long-lived process.

### Transport / lineage state

| object | fields | owner | role |
|---|---|---|---|
| request identity | `sequence`, `request_id`, `transaction_id` | Python `KernelStepRequest` and C++ parser | wire identity and retry ordering |
| physical-window identity | `global_step`, `case_local_bridge_step`, `integer_tick`, `time_s`, `dt_s` | request + C++ expected-lineage variables | distinguishes same-window retry from next window |
| endpoint/run identity | `run_id`, `case_id`, producer/consumer | request and worker | session and endpoint identity |
| process lineage | `last_sequence`, `expected_*`, `lineage_mode` | C++ worker process | expected next sequence and same-window retry rules |
| duplicate guards | `seen_request_ids`, `seen_transaction_ids` | C++ worker process | rejects reuse of IDs for the lifetime of that worker |
| frame envelope | `MAGIC`, length, message type | `protocol.py` / C++ frame reader | framing only; it is not a rollback checkpoint |

The wrapper currently derives transport IDs directly from the backend counter
(`step = attempted_advance_count`, `request_id = 910000 + step`,
`transaction_id = 1910000 + step`).

## B. `PreciceStructureFleetBackend`

File: `src/coupling/arbitrary_n_live_orchestration_v1/precice_backend.py`

This class does not own ANCF physical state or worker transport IDs.  It:

- creates the preCICE participant and mesh handles;
- writes displacement and reads force;
- calls preCICE `advance(dt)`;
- forwards `requires_writing_checkpoint()` and
  `requires_reading_checkpoint()` (lines 81-93).

It has no `snapshot()`, `restore()`, `request_id`, `transaction_id`,
`sequence`, or message-counter fields.  Consequently, preCICE checkpoint
signals are only triggers; the actual HH06 physical checkpoint is held by the
generic coordinator/backend layer.

## C. `GenericStructuralCoordinator`

File: `src/coupling/arbitrary_n_live_orchestration_v1/coordinator.py`

`CouplingCheckpoint` (lines 320-335) stores:

- checkpoint ID and manifest hash;
- coordinator iteration/time;
- a deep copy of `backend_state`;
- gathered slice IDs;
- `committed_step`.

It does **not** store:

- `request_id`;
- `transaction_id`;
- wire `sequence`;
- C++ worker `last_sequence`;
- C++ `seen_request_ids` / `seen_transaction_ids`;
- coordinator `attempted_structural_advances`.

`checkpoint()` (lines 465-478) calls `backend.snapshot()` before a tentative
advance.  `rollback()` (lines 480-494) calls `backend.restore()` and clears
force gather, iteration/time, last request/motion, tentative status, and
restores `committed_step`.  It does not communicate with the already-running
C++ worker to restore its transport state.

The coordinator's own `attempted_structural_advances` is incremented on every
`advance_if_complete()` but is not part of the checkpoint and is not restored.
This is separate from the backend counter that actually generates HH06 wire
IDs.

## D. `PersistentHH06KernelBackend`

File: `tools/hh06_single_slice_structure_0000_participant_v1/structure_0000_participant.py`

### Snapshot contents

Lines 353-354 snapshot:

```text
q, qdot, qddot,
attempted_advance_count,
committed_advance_count,
_pending
```

### Restore behavior

Lines 356-364 restore q/qdot/qddot and then explicitly assign:

```text
self.attempted_advance_count = snapshot["attempted"]
self.committed_advance_count = snapshot["committed"]
```

Thus the snapshot includes the backend's local ID-generating counters, and
rollback restores them to their pre-trial values.  The persistent worker
process is not restarted and its transport state is not restored.

### ID generation

Lines 373-379:

```text
attempted_advance_count += 1
sequence = attempted_advance_count
global_step = committed_advance_count + 1
case_local_bridge_step = sequence
request_id = 910000 + sequence
transaction_id = 1910000 + sequence
```

Therefore, after a Trial-A advance followed by the current production
rollback:

```text
worker has already seen: sequence=1, request_id=910001,
                         transaction_id=1910001
backend generates again: sequence=1, request_id=910001,
                          transaction_id=1910001
```

The current backend also sends `global_step=1` again, but that physical-window
identity is intentionally valid for an implicit retry.  The problem is the
reused wire identity and sequence, not the physical checkpoint q/qdot/qddot.

## E. Python persistent-IPC protocol

Files:

- `src/coupling/cpp_worker_persistent_ipc_v1/protocol.py`
- `src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py`

The frame envelope is `HEADER = struct.Struct("<8sII")`: magic, payload
length, and message type.  The kernel request prefix carries schema/protocol,
sequence, global step, bridge step, tick, time, dt, dimension, request ID and
transaction ID.  `KernelStepRequest` declares these fields at lines 528-546;
serialization places them in the prefix at lines 654-657.

Python validates the response identity against the request (sequence, global
step, bridge step, tick, time, transaction ID, request ID, run/case and
endpoint identities) in `validate_kernel_response()` (lines 766-779).  This
is a per-request echo/consistency check; it does not maintain a cross-request
monotonic-ID registry.

## F. C++ worker duplicate and retry rules

File: `src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp`

### Duplicate IDs

`process_step()` rejects zero or previously seen request/transaction IDs at
lines 288-292:

```text
seen_request_ids.count(request_id) != 0
|| seen_transaction_ids.count(transaction_id) != 0
=> return 18
```

After validation, IDs are inserted into the seen sets at lines 514-515.  The
sets live for the entire worker process (lines 802-805), so a normal physical
rollback cannot erase them.

### Sequence and lineage

The worker requires the incoming sequence to equal `expected_sequence` (line
495), and `main()` calls `process_step(..., last_sequence + 1, ...)` (line
848), incrementing `last_sequence` only after a valid response (line 868).

For an implicit retry, the worker's `allow_implicit_retry` branch (lines
545-569) permits the same physical window identity—same global step, bridge
step, tick, time and dt—**only with a fresh wire request/transaction identity**.
The source comment explicitly states that a parallel-implicit retry must issue
fresh binary request/transaction IDs.

`CFD_ANCF_ALLOW_IMPLICIT_RETRY` only enables this lineage branch; it does not
disable duplicate-ID rejection.

## G. Direct answers to the requested questions

### A. Which variables are physical state?

`q`, `qdot`, `qddot`, tentative/committed physical lifecycle flags, force
gather state, and the committed-window count.  These are the quantities that a
checkpoint must restore for correct ANCF physics.

### B. Which variables are transport state?

`sequence`, `request_id`, `transaction_id`, C++ `last_sequence`, expected
lineage fields, and the worker's seen-ID sets.  Frame magic/length/type are
framing state.  Run/case/endpoint identities and payload/model hashes are
transport/session identity state.

### C. Does the current checkpoint save transport IDs?

**Partially and incorrectly.** It saves the Python backend's
`attempted_advance_count` and `committed_advance_count`, which generate IDs,
but it does not save the worker's actual `last_sequence` or seen-ID sets, nor
any preCICE transport state.

### D. Does rollback restore transport IDs?

**Yes on the Python side, but not on the worker side.**
`PersistentHH06KernelBackend.restore()` resets the ID-generating counters;
the already-running C++ worker retains its prior sequence and duplicate-ID
sets.  This creates the mismatch.

### E. Where does the worker reject duplicate IDs?

`ancf_worker_main.cpp`, `process_step()`, lines 288-292, returns code **18**
when `request_id` or `transaction_id` is already in its process-lifetime
`seen_*` set.  Sequence mismatch is separately rejected at line 495 (return
code 13).

## H. Conclusion

The physical rollback path is correctly represented at the q/qdot/qddot level,
but the transport lifecycle is not checkpoint-compatible.  The production
backend resets the counters that generate wire IDs while the persistent worker
intentionally keeps IDs and sequence monotonic/process-unique.  The observed
HH06 Trial-B return code 18 is therefore the expected consequence of the
current lifecycle design, not an ANCF kernel or SHM1 failure.

No code was modified and no runtime was started in this audit.
