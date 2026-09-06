# STARTUP_STREAMWISE_FORCE_AND_FLUID_INITIALIZATION_AUDIT_V1

## Scope and immutable evidence

The failed coupled runtime `generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001` was read-only.  Two fresh, uncoupled four-step (`dt=0.005 s`, end time `0.02 s`) probes were generated in `runtime/startup_streamwise_force_and_fluid_initialization_audit_v1_run_002`: fixed cylinder and zero-motion `displacementLaplacian` mesh.  Neither launched preCICE or the structure worker.

## First correction force identity

All three slices have the same first correction at `t=0.005 s`:

| Quantity | Value |
|---|---:|
| Raw OpenFOAM-equivalent `Fx` | `155312.54389220272 N` |
| Raw OpenFOAM-equivalent `Fy` | `-187.65203374011548 N` |
| Unit span | `1 m` |
| Line force `Fx` | `155312.54389220272 N/m` |
| Tributary length | `16.666666666666668 m` |
| Integrated structural `Fx` | `2588542.398203379 N` |
| Integrated structural `Fy` | `-3127.5338956685914 N` |

The identity `F_slice = F_OF / unit_span * tributary_length` holds exactly at stored precision.  Therefore the large structural force is the correctly converted representation of a very large raw CFD force; it is not a new force-scaling failure.

The `t=0.005 s` zero-motion dynamic-mesh probe provides the missing raw decomposition for the exact same startup state:

| Component | `Fx` [N] | `Fy` [N] |
|---|---:|---:|
| Pressure | `153522.5621068` | `-193.3407973941` |
| Viscous | `1789.981785452` | `5.688763653973` |
| Total | `155312.543892252` | `-187.652033740127` |

The absolute `Fx` difference from the historical first exchanged force is below `5e-8 N`, proving that the exchanged value is the raw OpenFOAM surface force at the first advanced fluid time.  It is pressure-dominated (about 98.85% of total `Fx`).

## Freshness and initialization semantics

The preCICE log explicitly skips zero Force/Displacement samples at `t=0`, then maps `Force` at `t=0.005 s` after the first fluid solve.  The structure code writes displacement, calls `advance(dt)`, and only then reads Force.  No stale/default force route was found.

The actual initial fields are `U=uniform (1 0 0)` throughout the domain and at the inlet, `p=uniform 0`, while the cylinder has `movingWallVelocity` with zero velocity.  This is a cold impulsive enforcement of no-slip at a body embedded in a uniform moving field, not a flow field already compatible with the cylinder boundary.

There are no initial on-disk `phi`, `Uf`, or `meshPhi` fields.  In OpenFOAM 10, `createPhi.H` creates `phi` from `fvc::flux(U)` when it is absent and, for a dynamic mesh, `createUfIfPresent.H` creates `Uf` by interpolating `U`.  The mover writes `meshPhi` after its first update.  `pimpleFoam` then corrects `Uf` and makes `phi` relative to mesh motion.  The zero-motion probe constructs these fields normally and completes all four steps; no evidence identifies stale `phi`, stale `Uf`, or mesh-flux double application as the source of the first impulse.

## Isolation probes

| Probe | `Fx(0.005 s)` [N] | Pressure [N] | Viscous [N] | Result |
|---|---:|---:|---:|---|
| Fixed cylinder | `154850.737753531` | `153048.9262929` | `1801.811460631` | 4/4 steps complete |
| Zero-motion dynamic mesh | `155312.543892252` | `153522.5621068` | `1789.981785452` | 4/4 steps complete |

Both cases recover immediately: their total streamwise force is only about `3.2–3.5e3 N` by `t=0.01 s`.  The dynamic-mesh value is close to the fixed-mesh value (0.30% relative difference), but the extreme startup impulse exists even with no dynamic mesh.  The tiny prescribed-motion probe is unnecessary: fixed versus zero-motion already isolates the cause.

For the present physical scale, `0.5*rho*U^2*D = 500 N/m`; the first raw `Fx` is about 311 times this scale.  It is therefore `ORDER_OF_MAGNITUDE_SUSPICIOUS`, not a credible quasi-steady drag value.

The pressure impulse is not confined to a few pathological faces.  At `t=0.005 s`, the 40 cylinder-adjacent owner cells in the zero-motion dynamic probe range from `p=-91.4658` to `103.5557 m^2/s^2`; the upstream half (`x<0`) averages `67.4655 m^2/s^2` while the downstream half (`x>0`) averages `-57.2643 m^2/s^2`.  This broad front/back pressure jump, multiplied by `rho=1000 kg/m^3`, explains the pressure-dominated `Fx`; it is consistent with the imposed cold-start pressure correction rather than a small set of corrupted faces.

## Root cause and disposition

Classification: **INCONSISTENT_U_P_INITIALIZATION / startup transient**.  The cold uniform `U` plus zero-moving-wall cylinder causes a first-step pressure impulse before any nonzero structural `x/y` motion.  It is not an ANCF mapping/scaling bug, a preCICE force-timing bug, or a moving-mesh ALE-specific force-export bug.

This first force is sufficiently large to inject the subsequent streamwise structural response that causes mesh degradation; it is the current upstream blocker.

The single minimal remedy is to replace the coupled cold start with a documented, zero-interface-displacement fixed-cylinder precursor state containing boundary-compatible `U`, `p`, `phi`, and (for the dynamic case) `Uf/meshPhi` before the first FSI force exchange.  The precursor duration and acceptance checks must be frozen in a new contract; this audit does not alter initialization or run a coupled smoke.

## Observability change

`tools/generalized_force_metric_v2_and_0p1s_micro_smoke_v1/run_micro_smoke.py` now retains `forces.dat` every startup timestep, so pressure, viscous, and total surface forces can be reconciled with preCICE/LoadRecord conversion on any future bounded diagnostic.

## Decision

`NEXT_COUPLED_MICRO_SMOKE = NOT_AUTHORIZED` until a versioned precursor-initialization contract and its independent preflight are approved and implemented.
