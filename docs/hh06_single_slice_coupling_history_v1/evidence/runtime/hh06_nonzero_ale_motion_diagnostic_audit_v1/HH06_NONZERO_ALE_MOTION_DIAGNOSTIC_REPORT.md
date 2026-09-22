# HH06 NONZERO ALE MOTION DIAGNOSTIC AUDIT

## Final classification

`ALE_NOT_EXERCISED`

The real `Structure_0000` participant sent a deliberately nonzero
diagnostic-only displacement through preCICE, but the OpenFOAM adapter did not
produce a nonzero `pointDisplacement`/`cellDisplacement` fingerprint or mesh
motion during this one-window run. Therefore this is **not** an ALE pass and
is not a production HH06 physical result.

## Scope and protection

- One isolated real coupling window only; `dt = 0.0002 s`.
- Real `Fluid_0000` (`pimpleFoam`) and real `Structure_0000` wrapper.
- Real qualified SHM1 worker, SHA256:
  `69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF`.
- `parallel-implicit`; one rollback was observed.
- The original `slice0000` case, its worker, mesh, solver dictionaries and
  original socket were not modified; no original time directory was created.
- The OpenFOAM adapter was an isolated diagnostic build only. It did not
  replace the production adapter and did not alter solver equations.

## Nonzero Structure_0000 input

The copied, otherwise identical Structure_0000 wrapper used the production
ANCF worker, P1 `REF_NE32` q0, SHM1 and the normal section interpolation. A
diagnostic-only absolute transverse offset was added to the displacement sent
to preCICE:

```text
diagnostic offset = (0, 1.0e-4, 0) m
```

This offset is explicitly not an HH06 physical response and did not modify
the ANCF q/qdot/qddot state, the worker, SHM1, or the physical contract.

The participant record confirms:

```text
ANCF section motion       = (1.04520916e-7, 9.58869172e-8, 4.16387157e-4) m
displacement sent to Fluid= (1.04520916e-7, 1.00095887e-4, 4.16387157e-4) m
```

preCICE logged nonzero displacement exchange/convergence norms of `1.00e-4`
and `8.00e-5`, so the nonzero Structure-side input was not a zero-q0 test.

## Real rollback event sequence

```text
CHECKPOINT_WRITE             t=30.0000000 s
PRE_ROLLBACK_TRIAL           t=30.0002000 s
CHECKPOINT_READ_AFTER_RESTORE t=30.0000000 s
AFTER_INPUT_UPDATE           t=30.0000000 s
AFTER_INPUT_UPDATE           t=30.0002000 s
```

The coupling window completed successfully. No NaN, Inf, FPE, duplicate worker
ID, checkpoint error or preCICE failure occurred.

The fluid log contains preCICE `mapData` messages for `Displacement`, but it
does not contain a runtime `Reading coupling data...` event from the adapter.
Together with unchanged displacement-field hashes, this means the immediate
blocker is the fluid-side read-to-field/ALE application path, not a bad mesh
quality result. This observation is diagnostic only; no production adapter was
changed.

## Fingerprint result

The following hashes were identical before and immediately after rollback:

| object | result |
|---|---|
| `points` | identical, `84b09858d2e5c718` |
| `oldPoints` | identical, `84b09858d2e5c718` |
| `phi` | identical, `5e737856cbb4000a` |
| `cellVolume` | identical, `e49d59bd4291f4bd` |
| `faceArea` | identical, `a8d92acd46eb7fe9` |
| `pointDisplacement` | identical, `403a37f08d8872c4` |
| `cellDisplacement` | identical, `054f811aba347c5a` |
| `meshPhi` | present after restore, but not registered at checkpoint-write |

The adapter fingerprint therefore shows no nonzero ALE geometry state. The
`points` hash never changed, and the mesh-motion diagnostics were:

```text
max point displacement = 0
max cell displacement  = 0
max mesh velocity      = 0 m/s
mesh Courant           = 0
```

The fluid solver Courant maximum remained `0.4182184878`. Turbulence fields
were finite (`k` approximately `2.70e-10 ... 1.59e-2`, `omega` approximately
`1.98 ... 9.38e4`); no numerical-health failure was observed.

## Required judgements

### A. Did nonzero Structure displacement drive ALE?

**Not demonstrated.** Structure_0000 sent a nonzero displacement and preCICE
reported the mapped displacement, but the OpenFOAM displacement fields and
mesh point hash remained unchanged in the observable runtime state.

### B. Was there a mesh-velocity spike?

**No spike observed.** This is a consequence of zero observed mesh motion, not
evidence that nonzero ALE motion is stable.

### C. Did meshPhi become abnormal before Co growth?

**No abnormality observed.** `meshPhi` did not show a nonzero/abnormal motion
signature, and the maximum fluid Co stayed below `0.42`.

### D. Was nonzero mesh state consistent before/after rollback?

**Not evaluable for nonzero ALE.** The zero-motion geometry state was restored
consistently, but no nonzero mesh state was materialized. The checkpoint-write
`meshPhi` hash was also unavailable because the object was not registered at
that point.

## Evidence files

- `fluid_rollback_fingerprint.jsonl` — SHA256
  `E801EC4ED4DAA67404D4C562895056F824BF2EC63C6D5529D3AB3A5C12AEFD45`
- `participant.stdout` — SHA256
  `3D9840A7897B2837E3B137DA3828A1F148260FA0B03E76FAC9EB2ED9397F1387`
- `fluid.stdout` — SHA256
  `7098216C7AE6B9E630143A6848F0A27C1734D9FEF7B3A548F52A1C77C1E2DEFB`
- diagnostic adapter SHA256
  `638d60dc9236e8ec38f656237fc9f658f3b4589b0af1acb66ed23c0683cbaad9`

No follow-up CFD or longer FSI run was started.
