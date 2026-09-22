# HH06 Structure_0000 Offline Runtime Qualification

## Final classification

```text
PASS_HH06_STRUCTURE_OFFLINE_RUNTIME_QUALIFICATION
```

The transport-ID rollback repair passed an actual production backend / C++
worker offline run.  The test used one non-zero, test-only cross-flow force and
performed Trial A, production checkpoint rollback, Trial B replay, and one
commit.  No preCICE initialization or handshake was performed.

## Runtime and provenance

- Case: `/home/machao/OpenFOAM/coupling/singal_slice/slice0000`
- Qualified worker:
  `/home/machao/OpenFOAM/coupling/singal_slice/slice0000/cfd_ancf_ancf_kernel_worker_shm1_qualified`
- Worker SHA256: `69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF`
- Worker size: `2647128` bytes
- Backend source:
  `tools/hh06_single_slice_structure_0000_participant_v1/structure_0000_participant.py`
- Backend source SHA256:
  `C5401DDF05C0C312B69F2C6DDE0C8CC130BCCE16753CDD0E5258CFBBE95D1C46`
- Worker exit code: `0`

The raw harness result is preserved at
`HH06_OFFLINE_RUNTIME_QUALIFICATION_RESULT_RETRY_RAW.json`; the previous
pre-fix failure evidence remains at
`HH06_OFFLINE_RUNTIME_QUALIFICATION_RESULT_PRE_TRANSPORT_FIX.json`.

## Frozen HH06 model

- `L=13.12 m`, `Ne=32`, `nodes=33`, `DOF=198`
- `q0`: P1 `REF_NE32` static equilibrium
- `v0`: zero vector
- `dt=0.0002 s`
- SHM1 region count: `1`
- SHM1 region: `[0.0, 13.12] m`
- added mass per length: `[0.616, 0.616, 0.0] kg/m`
- damping per length: `[0.0, 0.0, 0.0] N s/m²`
- SHM1 model offset: `176` bytes; version: `1`

The physical advance therefore used the wet SHM1 model and did not silently
fall back to a dry model.

## Test stimulus

The interface contract identifies `y` as cross-flow.  The qualification used
the deterministic test-only resultant

```text
F = [0, 1, 0] N at s=2.97 m
```

This is a runtime stimulus only and is not HH06 fluid data.

## Trial A and checkpoint A

Checkpoint A was taken before the first trial, with committed physical step
`0`.  The checkpoint q/qdot/qddot hashes were:

```text
q     = E1BA7FC759244D8E0EF884F256980C6BD815C64932B0318FD021395815B1A9F0
qdot  = C87499548F9EFBD98C824A95A664AF38F414EFB1C9EEDE544E55E019473D6B24
qddot = C87499548F9EFBD98C824A95A664AF38F414EFB1C9EEDE544E55E019473D6B24
```

Trial A completed one step with 3 Newton iterations and residual
`7.826941494926132e-08`.  The state changed non-trivially and all state values
were finite.

Trial A physical identity:

```text
global_step=1, case_local_bridge_step=1, time=0.0002 s, dt=0.0002 s
```

Trial A transport identity:

```text
sequence=1, request_id=910001, transaction_id=1910001
```

## Rollback and Trial B

Production coordinator rollback restored q, qdot, and qddot exactly and
cleared the tentative state.  Transport counters were not restored.

Trial B used the same physical window:

```text
global_step=1, case_local_bridge_step=1, time=0.0002 s, dt=0.0002 s
```

but fresh monotonic transport identity:

```text
sequence=2, request_id=910002, transaction_id=1910002
```

Thus all three transport identities are strictly greater than Trial A while
all physical-window identity fields remain equal, as required by the C++
implicit-retry lineage contract.

## Deterministic replay

Trial B completed successfully.  The existing exact replay comparison gave:

```text
max_abs_diff_q                         = 0.0
max_abs_diff_qdot                      = 0.0
max_abs_diff_qddot                     = 0.0
max_abs_diff_section_displacement_m   = 0.0
```

The Trial B state was then committed successfully (`committed_step=1`).

## Ownership conclusion

The repair has the intended ownership split:

| Quantity | Rollback behavior |
|---|---|
| q, qdot, qddot | restored from checkpoint |
| tentative/pending physical state | restored/cleared according to production coordinator lifecycle |
| committed physical window | restored from checkpoint; incremented only on commit |
| sequence/request_id/transaction_id | session-monotonic; never restored |
| C++ duplicate-ID detection | unchanged and still enabled |

## Execution boundary audit

- OpenFOAM: **not run**
- `Fluid_0000`: **not run**
- preCICE initialize/handshake: **not run**
- `launch.sh`: **not run**
- CFD time directory: **not created**
- ANCF physical runtime: **only the authorized single offline worker step**
- ANCF kernel/source: **not modified**
- SHM1 protocol: **not modified**
- HH06 contract: **not modified**

## Next phase

```text
authorized_next_phase = HH06_PRECICE_HANDSHAKE_QUALIFICATION
```

No preCICE handshake was started automatically.  Execution stops here pending
manual confirmation.
