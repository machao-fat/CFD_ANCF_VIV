# HH06 single-slice force unit-chain audit

## Result

`FORCE_UNIT_CHAIN = PASS`

The pre-gate used one isolated real `Fluid_0000` / `Structure_0000` coupling window with the qualified SHM1 worker. No diagnostic displacement offset was applied. Both processes returned `0`.

The audit-only adapter build changed only observability in `Interface.C`: it recorded the exact component sum of the 200 face-force values immediately before `preCICE::writeData()`. It did not change the buffer. The formal multiwindow candidate adapter was not overwritten.

## Frozen conversion

```text
F_slice = (F_raw / Lz) * DeltaL
Lz      = 0.028 m
DeltaL  = 1.98 m
factor  = 70.71428571428571
```

The only dimensional conversion is in production `ForceSample.from_openfoam_integrated()` (`coordinator.py`, lines 73-80). `GenericStructuralCoordinator._build_request()` then places `sample.values` unchanged in `WorkerRequest.slice_force_N`; the HH06 backend places that tuple unchanged in `KernelStepRequest.slice_force`.

## Same-iteration numerical chain

The nonzero second implicit iteration of physical window 1 gave:

| Stage | X | Y | Unit |
|---|---:|---:|---|
| OpenFOAM raw integrated force (sum of 200 adapter face-force values) | 0.06440713207168003 | 0.05908675094604829 | N |
| Adapter `preCICE::writeData()` component sum | 0.06440713207168003 | 0.05908675094604829 | N |
| Conservative mapping to the single Structure point | 0.06440713207168003 | 0.05908675094604829 | N |
| Structure participant received Force | 0.06440713207168003 | 0.05908675094604829 | N |
| Per-unit-span force (`/0.028`) | 2.3002547168457155 | 2.1102411052160104 | N/m |
| Strip resultant (`*1.98`) | 4.554504339354517 | 4.178277388327700 | N |
| `WorkerRequest.slice_force_N` | 4.554504339354517 | 4.178277388327700 | N |
| ANCF `KernelStepRequest.slice_force` | 4.554504339354517 | 4.178277388327700 | N |

The initial implicit exchange correctly carried zero force because no Fluid result was yet available. It was not used as the nonzero scaling proof.

## Closure checks

- adapter-write sum vs mapped Structure force: exact in recorded double precision;
- mapped force vs participant-received force: exact;
- computed `F_raw / 0.028 * 1.98` vs `ForceSample.values`: exact;
- `ForceSample.values` vs worker physical resultant: exact;
- observed applied/raw ratio: `70.71428571428571`;
- no extra `0.028` or `1.98` factor was observed;
- preCICE mapping is conservative and performs no dimensional scaling.

Therefore scaling occurs exactly once, after the mapped raw OpenFOAM resultant is read by `Structure_0000` and before the physical worker request is serialized.

## Evidence and identities

- adapter force trace: `phase_a_force_gate/adapter_force_trace.jsonl`
- Structure/worker trace: `phase_a_force_gate/structure_force_trace.jsonl`
- Fluid log: `phase_a_force_gate/fluid.stdout`
- Structure log: `phase_a_force_gate/participant.stdout`
- audit-only adapter SHA256: `EEAA70CC2AB72E513AB69945866A6F5AE439786E54B2609AF2444B158494F002`
- frozen candidate `Adapter.C` SHA256 remained: `710F45FBA682442CBEC979D6993A24B2C530B0E592B62C18041D429CA4DD6301`
- production coordinator SHA256: `E612D5BFDFFB54DB07A7A325934CBB9D1CFF65EC22B48639AD085B79CB0A90A3`

This PASS opens Phase B/C preparation. It is not a 25-window or production-physics result.
