# HH06 Structure_0000 offline runtime qualification report

## Result

**Classification:** `DO_NOT_PASS`

**Primary blocker:** `PRODUCTION_BACKEND_ROLLBACK_REUSES_TRANSPORT_IDS`

The qualified worker initialized and completed one real, non-zero production
ANCF step.  The production coordinator restored the physical checkpoint
correctly, but the current HH06 persistent backend also restored its attempted
transport counter.  The replay consequently reused the first wire request and
transaction IDs.  The worker correctly rejected that duplicate lineage and
closed with return code 18 before a second physical step was accepted.

This is a fail-closed runtime-qualification result; no source, protocol,
physical parameter, XML, or CFD case was changed to hide the issue.

## Frozen model and initial state

- P1 artifact: `D:/CFD/CFD_ANCF_VIV_reentry_runtime/HH06_P1_WET_MODAL_STRUCTURAL_GATE/ancf_static.raw`
- P1 artifact SHA256:
  `B298979244F67E23D02A63566E718CCB1F8897570C12B0AAB98F7CBBF6577091`
- selector: `REF_NE32`, Q count 198
- q0 packed-state SHA256:
  `E1BA7FC759244D8E0EF884F256980C6BD815C64932B0318FD021395815B1A9F0`
- v0: zero vector, 198 entries
- geometry: `L=13.12 m`, `Ne=32`, `nodes=33`, `DOF=198`
- benchmark top tension: `1175.0 N`
- equilibrium reaction tension: `1188.28 N` (not substituted for benchmark input)
- `dt=0.0002 s`

The initial-state initialization passed with all q/qdot/qddot values finite.

## SHM1 identity used by the physical request

The actual production `KernelModel` contained exactly one region:

```text
[0.0, 13.12] m
added mass per length = [0.616, 0.616, 0.0] kg/m
linear damping per length = [0.0, 0.0, 0.0] N s/m^2
```

The serialized production model evidence was:

- model bytes SHA256:
  `1CF5189B5270DE532730D37D9962767284B40D80BCA6FBEF9A0CDAF511616164`
- SHM1 offset: 176 bytes in model bytes
- marker bytes: `53484d31` (`0x314D4853`)
- version: 1
- region count: 1
- region raw bytes SHA256:
  `916E2FDE1563525D11EE53391493815F691C916CB707F55C45B10A277CB1A87F`

Thus the step below was not a dry/legacy model: it used the qualified SHM1
wet model.

## Test-only force and location

The frozen interface contract defines `x=inline`, `y=crossflow`, `z` as the
reference/spanwise axis.  A deterministic test-only cross-flow resultant was
therefore selected:

```text
F_slice = [0, 1, 0] N at s = 2.97 m
```

To exercise the production OpenFOAM-integrated-force conversion without
changing the resultant, the equivalent raw force supplied to
`ForceSample.from_openfoam_integrated` was
`[0, 0.014141414141414142, 0] N`, using `0.028 m` unit span and `1.98 m`
slice length.  This force is only a runtime test stimulus; it is not claimed
as HH06 fluid data.

## Qualification sequence and evidence

### Initialization and checkpoint A

The qualified worker started and returned a valid initialization
acknowledgement.  The production `GenericStructuralCoordinator` then created
checkpoint `hh06-offline-checkpoint-A` before any trial advance.  q, qdot and
qddot hashes in checkpoint A match the initial state above.

### Trial A

One exact step (`dt=0.0002 s`) completed through the production
`PersistentHH06KernelBackend` and qualified C++ worker:

- Newton iterations: 3
- residual: `7.826941494926132e-08`
- output q SHA256:
  `094513E6CA2DC91D1C6766FE19D0FC05AF4CAC3B7432B4E25446489CB841EBB9`
- section displacement at `s=2.97 m` (absolute section position):
  `[0.0, 2.294891131458091e-08, 2.970416387157332] m`
- cross-flow displacement relative to its reference position:
  `2.294891131458091e-08 m`
- all q/qdot/qddot values finite
- state changed non-trivially: **Yes**

### Rollback

The production coordinator rollback restored q, qdot and qddot exactly to
checkpoint A and cleared the tentative state.  However, the backend restored
`attempted_advance_count` from 1 back to 0.  This is a physical-state rollback
but not a transport-ID-monotonic rollback implementation.

### Trial B replay

The same production force, time, model and checkpoint state were submitted
again.  Because the backend counter had been restored, it generated the same
wire sequence/request/transaction IDs as Trial A.  The worker rejected the
duplicate request lineage; no second physical response was returned:

- replay: **FAIL**
- backend exception: `HH06ContractError: worker response header missing at step 1`
- worker return code: `18`
- worker stderr: empty

Therefore B1/B2 deterministic comparison and post-replay commit were not
authorized.  No permanent physical commit was recorded.

## Interpretation and minimum diagnosis

The worker itself is qualified and Trial A proves that the real SHM1 model,
P1 q0 and one-step ANCF integration are executable.  The failed qualification
is specifically the production HH06 backend's rollback bookkeeping:

```text
physical state: restored correctly
transport IDs: incorrectly reused after restore
```

The minimal next diagnostic is to repair or replace only the HH06 backend's
rollback counter semantics so that a retry uses fresh monotonically increasing
wire IDs while retaining the checkpoint physical state.  That repair was not
performed in this run, because the present task requires fail-closed evidence
and forbids unapproved source changes.

## Execution boundary audit

- OpenFOAM: **not run**
- preCICE initialize/handshake: **not run**
- Fluid_0000: **not run**
- `launch.sh`: **not run**
- CFD time advance: **not run**
- new OpenFOAM time directory: **not created**
- ANCF kernel/source modified: **No**
- SHM1 protocol modified: **No**
- old worker overwritten/deleted: **No**

Machine-readable details are in
`HH06_OFFLINE_RUNTIME_QUALIFICATION_RESULT.json`.  The actual harness is
`HH06_OFFLINE_RUNTIME_QUALIFICATION.py`.
