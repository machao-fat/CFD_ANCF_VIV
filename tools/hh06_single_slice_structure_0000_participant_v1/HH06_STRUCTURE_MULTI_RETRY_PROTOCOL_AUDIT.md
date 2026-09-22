# HH06 Structure Multi-Retry Protocol Audit

## Scope

This audit is read-only with respect to production code, coupling
configuration, mesh, solver settings, physical parameters, and runtime logs.
No OpenFOAM, preCICE, ANCF worker, or 50-window calculation was started.

Audited evidence:

- `PersistentHH06KernelBackend` and the HH06 `Structure_0000` loop;
- `GenericStructuralCoordinator` checkpoint lifecycle;
- `PreciceStructureFleetBackend` checkpoint signals;
- the frozen C++ worker source and qualified binary identity;
- existing `max-iterations=2`, `5`, and `10` sensitivity logs.

## Final status

```text
STRUCTURE_MULTI_RETRY_STATUS = WORKER_PROTOCOL_SINGLE_RETRY_LIMIT
ROOT_CAUSE = CFD_ANCF_ALLOW_IMPLICIT_RETRY_NOT_ENABLED_IN_SENSITIVITY_RUNNER
CHECKPOINT_RESTORE_INCOMPLETE = false
WORKER_CRASH_UNRELATED = false
```

This is a runtime protocol-gate limit, not an intrinsic limitation of the
qualified binary. The deployed binary contains the multi-retry branch, but it
is disabled unless `CFD_ANCF_ALLOW_IMPLICIT_RETRY=1` is present in the worker
process environment.

## 1. Checkpoint contents and ownership

### Backend physical snapshot

`PersistentHH06KernelBackend.snapshot()` stores:

- `q`;
- `qdot`;
- `qddot`;
- committed physical-window count;
- tentative-state flag (`pending`).

It deliberately does not store or restore:

- wire `sequence`;
- `request_id`;
- `transaction_id`;
- the three transport counter generators;
- diagnostic attempted-advance count.

This separation is correct. Transport identities remain monotonic across a
physical rollback.

### Coordinator checkpoint

`CouplingCheckpoint` also records checkpoint identity, manifest identity,
coordinator iteration/time fields, gathered slice IDs, and committed step.
The live HH06 loop writes the checkpoint before the force sample is gathered,
so coordinator iteration/time may be `None` at checkpoint creation. The
physical request identity is nevertheless deterministically re-issued with
the same physical window, `time_s`, and `dt_s` on retry.

There is no additional opaque ANCF integration state outside
`q/qdot/qddot` that must be restored by this wrapper: each C++ request carries
the complete physical state and reconstructs the step from that payload. The
persistent worker retains only transport/lineage state across requests.

## 2. Repeated rollback support in Python

The coordinator keeps the same active checkpoint after `rollback()` and
clears it only after `commit()`. Its rollback path restores the backend
snapshot, clears tentative gather/motion state, and leaves transport counters
monotonic.

The HH06 loop has no hard-coded retry-count limit. Every preCICE
`requires_reading_checkpoint()` request calls `coordinator.rollback()` and
continues the same physical window.

Existing `max-iterations=5` and `10` traces prove that this path completed two
successive rollback cycles in physical window 1:

| coupling iteration | wire sequence | request ID | transaction ID | result |
|---:|---:|---:|---:|---|
| 1 | 1 | 910001 | 1910001 | worker response received; rollback completed |
| 2 | 2 | 910002 | 1910002 | worker response received; rollback completed |
| 3 | 3 | 910003 | 1910003 | request sent; no response header |
| 4 | - | - | - | not reached |
| 5 | - | - | - | not reached |

After both completed rollbacks, the trace returns to the same checkpoint
hashes:

```text
q      = e1ba7fc759244d8e0ef884f256980c6bd815c64932b0318fd021395815b1a9f0
qdot   = c87499548f9efbd98c824a95a664af38f414efb1c9eede544e55e019473d6b24
qddot  = c87499548f9efbd98c824a95a664af38f414efb1c9eede544e55e019473d6b24
```

Therefore the evidence does not support
`CHECKPOINT_RESTORE_INCOMPLETE` as the sequence-3 cause.

## 3. C++ worker sequence state machine

The qualified worker source uses a process-lifetime `last_sequence`,
process-unique request/transaction ID sets, physical-window lineage fields,
and an environment-controlled `allow_implicit_retry` flag.

The first two requests establish implicit lineage:

- sequence 1 seeds the lineage;
- sequence 2 is allowed to reuse the same physical-window identity and sets
  implicit lineage mode.

For an odd sequence greater than 1, such as sequence 3, a same-window retry is
accepted only when `allow_implicit_retry` is true. Otherwise the normal
lineage branch requires sequence 3 to be the next physical window.

The binary used by both failing sensitivity cases is:

```text
/home/machao/OpenFOAM/coupling/singal_slice/slice0000/
cfd_ancf_ancf_kernel_worker_shm1_qualified
SHA256 = 69f045eb7f4576e5178d10711f0f265d7458282a7a4ecbcb860a913ada45beef
```

Read-only binary inspection confirms that it contains:

- `CFD_ANCF_ALLOW_IMPLICIT_RETRY`;
- `worker implicit retry-or-next-window identity mismatch at sequence`;
- `worker identity continuity mismatch at sequence`.

Thus the deployed binary is multi-retry capable when its explicit runtime gate
is enabled.

## 4. Why sequence 3 failed

The sensitivity runner does not export
`CFD_ANCF_ALLOW_IMPLICIT_RETRY=1`. The earlier offline qualification and the
separate retry script do export it, which confirms that the variable is part
of the intended worker runtime contract.

In the `max-iterations=2` run, sequence 3 belongs to physical window 2 because
window 1 is forcibly completed at iteration 2. It therefore satisfies the
normal next-window lineage rule and succeeds.

In the `max-iterations=5` and `10` runs, sequence 3 is still a retry of
physical window 1. With the gate disabled, the C++ worker rejects that
identity, exits without writing a response frame, and Python observes EOF as:

```text
HH06ContractError: worker response header missing at sequence 3
```

The later Fluid broken pipe is a downstream consequence of Structure_0000
exiting; it is not the initiating failure.

## 5. Requested classification

### A. `WORKER_PROTOCOL_SINGLE_RETRY_LIMIT`

**Confirmed for the audited runtime configuration.** More precisely, this is
an explicit worker protocol feature gate that was not enabled in the
sensitivity runner.

### B. `CHECKPOINT_RESTORE_INCOMPLETE`

**Not supported.** Two consecutive rollbacks restore identical
`q/qdot/qddot` hashes, preserve the checkpoint, and advance transport IDs
monotonically.

### C. `WORKER_CRASH_UNRELATED`

**Not supported.** The failure is deterministic at the first same-window odd
retry (sequence 3) in both max-5 and max-10 cases and exactly matches the
disabled lineage-gate behavior.

## Boundary

No repair was made. No configuration was modified. No runtime was started.
Any future repair or requalification requires separate authorization.

