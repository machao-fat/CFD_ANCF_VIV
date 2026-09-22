# HH06 rollback / transport-ID fix design

## Status and scope

This document is a design-only patch plan for
`PRODUCTION_BACKEND_ROLLBACK_REUSES_TRANSPORT_IDS`.

No source code, contract, protocol, worker binary, mesh, XML, or physical
parameter was modified.  No compilation was performed.  No OpenFOAM,
preCICE, or ANCF advance was run.

The design preserves the already passing physical rollback semantics and
changes only ownership of transport identity counters.

## 1. Root cause

The HH06 backend currently overloads one counter for two different concerns:

```text
attempted_advance_count
    -> sequence
    -> case_local_bridge_step
    -> request_id = 910000 + step
    -> transaction_id = 1910000 + step
```

`PersistentHH06KernelBackend.snapshot()` stores `attempted` and
`committed`; `restore()` restores both.  Consequently, after Trial A and a
physical rollback, the backend emits the same sequence/request/transaction
identity again.

The persistent C++ worker intentionally does not roll back its transport
state.  It retains `last_sequence` and the process-lifetime
`seen_request_ids` / `seen_transaction_ids`.  A repeated request or
transaction ID is rejected with return code 18.  This duplicate rejection is
correct and must remain enabled.

There is a second coupled issue: `case_local_bridge_step` is currently also
derived from the transport attempt counter.  A correct retry needs a fresh
wire sequence but the same physical-window bridge identity.  Therefore the
fix must split transport sequence from physical-window identity, not merely
stop restoring one integer.

## 2. Affected files

### Functional patch location (minimal)

`tools/hh06_single_slice_structure_0000_participant_v1/structure_0000_participant.py`

Specifically, `PersistentHH06KernelBackend`:

- constructor counter initialization;
- `snapshot()`;
- `restore()`;
- `advance()` request construction;
- `commit()` counter semantics.

### Review / possible compatibility-only location

`src/coupling/arbitrary_n_live_orchestration_v1/coordinator.py`

No numerical change is required there.  Its `CouplingCheckpoint` should remain
a physical checkpoint.  Documentation/type comments and regression tests may
be updated to make clear that backend transport state is deliberately absent.
The coordinator's `attempted_structural_advances` remains a diagnostic
monotonic counter and is not a wire ID source.

### Test locations to add or update after approval

- HH06 wrapper rollback/replay tests;
- persistent-IPC identity/lineage tests;
- coordinator checkpoint serialization tests.

### Files that must not be changed for this fix

- `ancf_kernel.cpp` / `ancf_kernel.hpp`;
- `ancf_worker_main.cpp`;
- `kernel_protocol.py` and `protocol.py` wire schema;
- HH06 physics contracts and q0 artifact;
- `precice-config.xml`;
- OpenFOAM case files or `launch.sh`.

## 3. Minimal patch locations and behavior

### 3.1 Split physical and transport counters in the HH06 backend

Keep a physical committed-window counter:

```text
committed_advance_count
```

Add transport-only monotonic counters, for example:

```text
transport_sequence_counter
transport_request_id_counter
transport_transaction_id_counter
```

They are initialized once per worker session and are never restored from an
implicit-coupling checkpoint.  A single monotonic transport-attempt counter
may derive the two ID counters, but the ownership must be explicit and
overflow must fail closed.

### 3.2 Make checkpoint state physical-only

`snapshot()` should contain only the state needed to restore the solver:

- `q`, `qdot`, `qddot`;
- tentative/pending state;
- `committed_advance_count` (the physical committed-window index).

It must not serialize transport sequence, request ID, transaction ID, or any
worker process identity set.

For compatibility with old in-memory snapshots, `restore()` may tolerate an
old `attempted` key but must ignore it and must never assign it to a transport
counter.

### 3.3 Build retry requests with separate identities

For every attempted wire request:

```text
transport_sequence_counter += 1
sequence       = transport_sequence_counter
request_id     = fresh monotonic request identity
transaction_id = fresh monotonic transaction identity
```

For the physical window:

```text
global_step          = committed_advance_count + 1
case_local_bridge_step = committed_advance_count + 1
```

Thus the required first-window sequence is:

```text
Trial A: sequence=1, global_step=1, bridge_step=1, fresh IDs A
Retry B: sequence=2, global_step=1, bridge_step=1, fresh IDs B
Next C:  sequence=3, global_step=2, bridge_step=2, fresh IDs C
```

The worker's implicit-retry branch explicitly accepts this same-window
physical identity with a fresh wire identity.  No change to the C++ worker is
needed.

### 3.4 Commit behavior

`commit()` continues to increment only `committed_advance_count` and clears
the tentative flag.  It must not reset or decrement any transport counter.

### 3.5 Coordinator behavior

`GenericStructuralCoordinator.checkpoint()` and `rollback()` already restore
the physical backend snapshot and clear tentative force/motion bookkeeping.
No transport counter should be added to `CouplingCheckpoint`.

The only recommended coordinator-side change is an explicit comment/assertion
that `backend_state` is physical solver state and that transport identity is
session-monotonic and external to a checkpoint.

## 4. Before/after state ownership

| State / counter | Current owner | Current checkpoint behavior | Proposed owner | Proposed rollback behavior |
|---|---|---|---|---|
| `q`, `qdot`, `qddot` | HH06 backend / request | saved and restored | physical solver state | restore exactly |
| `_pending`, `_pending_advance` | backend/coordinator | cleared/restored as tentative lifecycle | physical solver lifecycle | clear tentative trial |
| `committed_advance_count` | HH06 backend | saved/restored | physical window index | restore to checkpoint |
| coordinator `committed_step` | coordinator | saved/restored | physical window index | restore to checkpoint |
| `attempted_advance_count` | HH06 backend | currently saved/restored | split; no longer a transport identity | do not restore transport portion |
| `sequence` | derived from attempted count | indirectly reset | transport state | strictly monotonic, never restore |
| `request_id` | derived from attempted count | indirectly reused | transport state | fresh ID on every wire attempt |
| `transaction_id` | derived from attempted count | indirectly reused | transport state | fresh ID on every wire attempt |
| `case_local_bridge_step` | currently tied to attempt sequence | indirectly reset | physical-window identity | same value on same-window retry |
| `global_step` | `committed_advance_count+1` | restored | physical-window identity | same value on retry |
| `integer_tick`, `time_s`, `dt_s` | request physical identity | regenerated | physical-window identity | same value on retry |
| worker `last_sequence` | C++ worker process | never checkpointed | transport state | never rollback |
| worker seen-ID sets | C++ worker process | never checkpointed | transport state | never clear during session |
| coordinator `attempted_structural_advances` | coordinator diagnostic | not checkpointed | diagnostic counter | may remain monotonic; never wire identity |

## 5. Risk analysis

### Low risk / desired effects

- q/qdot/qddot rollback semantics remain unchanged.
- SHM1 serialization and ANCF kernel numerical implementation are untouched.
- The worker's duplicate detection continues to reject accidental replay of an
  already-used transport identity.
- A legal implicit retry becomes representable: fresh sequence/IDs with the
  same physical window identity.

### Main implementation risks

1. **Bridge-step confusion:** using the fresh transport sequence as
   `case_local_bridge_step` would still fail the worker's same-window retry
   identity test.  This must be covered by a dedicated retry fixture.
2. **Counter overflow:** request and transaction IDs must fail closed before
   wrapping; silent wraparound would defeat duplicate detection.
3. **Old checkpoint objects:** old snapshots may contain `attempted`; restore
   must ignore it rather than assigning it to the new transport counter.
4. **Session restart semantics:** a worker restart starts a new process and
   therefore a new seen-ID set.  This design covers in-process implicit
   rollback; restart/recovery needs a separate run/session identity policy.
5. **Regression expectations:** tests that currently assert
   `snapshot()["attempted"]` must be updated to distinguish physical state
   from transport state rather than restoring the counter.

### Why not relax worker duplicate detection?

Disabling duplicate detection would allow a stale or accidentally repeated
trial to appear valid, permit double counting of a coupling attempt, and hide
incorrect rollback semantics.  The worker's return code 18 is the correct
fail-closed behavior.  The producer must issue fresh IDs instead.

## 6. Required post-approval tests

The eventual patch should be qualified offline with no CFD:

1. Trial A: `(sequence, global, bridge, request, transaction) = (1,1,1,A,A)`.
2. Rollback: q/qdot/qddot return exactly; transport counter remains at 1.
3. Trial B: `(2,1,1,B,B)` with `B != A`; worker accepts under
   `CFD_ANCF_ALLOW_IMPLICIT_RETRY=1`.
4. Commit B; next physical request is `(3,2,2,C,C)`.
5. Deliberate duplicate A is still rejected with worker return code 18.
6. Verify checkpoint JSON contains no transport identity fields.
7. Verify q/qdot/qddot B1/B2 deterministic equality under the existing
   repository tolerance.

## 7. Design conclusion

The minimum safe repair is a Python HH06 backend state-ownership change:

```text
checkpoint/rollback restores physical solver state only;
transport sequence/request/transaction identities remain session-monotonic.
```

No C++ worker, SHM1 protocol, ANCF kernel, preCICE XML, or HH06 physical
contract change is justified.  Worker duplicate detection must remain enabled.

This design is not an implementation approval; the next phase requires an
explicit authorization to patch and then run the offline retry qualification.
