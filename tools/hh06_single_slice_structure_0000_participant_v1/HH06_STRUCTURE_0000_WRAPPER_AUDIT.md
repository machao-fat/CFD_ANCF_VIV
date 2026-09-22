# HH06 `Structure_0000` wrapper implementation audit

## Scope

This change adds only the HH06 single-slice adapter.  It does not change
`ancf_kernel.cpp`, `ancf_kernel.hpp`, `ancf_worker_main.cpp`, OpenFOAM files,
the preCICE XML, or any numerical artifact.  No OpenFOAM, preCICE, worker, or
ANCF process was started.

## Implemented path

```text
preCICE Structure_0000
  -> PreciceStructureFleetBackend
  -> GenericStructuralCoordinator
  -> PersistentHH06KernelBackend
  -> existing persistent ANCF worker
```

The structure side registers one coupling point.  It reads one mapped
resultant force, applies the frozen `N -> N/m -> N` strip conversion exactly
once, and evaluates the absolute section displacement at `s=2.97 m`.  The
full 33-node/198-DOF ANCF state and generalized load assembly remain internal
to the coordinator/worker path; no CFD-face-to-ANCF-node mapping is present.

The implicit loop snapshots before a tentative window, advances the worker,
and restores the snapshot whenever preCICE requests a checkpoint read.  A
window is counted only after the preCICE iteration is accepted.

## Offline checks

| Check | Result |
|---|---|
| Python bytecode compilation | PASS |
| Normal module import | PASS |
| Contract JSON/XML-independent audit | PASS for geometry, P1 Q0, mapping, participant identity and tension separation |
| Live preCICE initialization | NOT RUN |
| Worker start / ANCF integration | NOT RUN |

The selected P1 state is `REF_NE32`, 198 values, loaded from:

`D:\CFD\CFD_ANCF_VIV_reentry_runtime\HH06_P1_WET_MODAL_STRUCTURAL_GATE\ancf_static.raw`

The observed artifact SHA256 is:

`b298979244f67e23d02a63566e718ccb1f8897570c12b0aab98f7cbbf6577091`

The selected Q-vector SHA256 is:

`e1ba7fc759244d8e0ef884f256980c6bd815c64932b0318fd021395815b1a9f0`

## Remaining runtime blocker

The checked-out repository Python wire protocol at the validation branch does
not expose the `SHM1` `SpanwiseHydrodynamicRegion` extension, while the target
`slice0000` C++ source contains that extension.  The wrapper therefore fails
closed with `hydrodynamic_wire_extension` rather than silently dropping the
P1 added mass.  The case remains `READY_FOR_DRY_RUN`; no live handshake or
time integration is authorized until the Python wire protocol and target
worker ABI are selected from the same SHM1-capable revision.

Wrapper source SHA256:

`7527495AAFC00E0198710D43D67008C988E069C60EFA6288A88FDEEE20471286`
