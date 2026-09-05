# CORRECTED_MOVING_MESH_COUPLING_REVALIDATION_V1

## Gate decision

`CORRECTED_COUPLED_1S_SMOKE = FAIL`.

The fresh runtime was `runtime/corrected_moving_mesh_1s_run_001`.  No coupled
window committed, and Phase B was not started.

## Unique minimal blocker

OpenFOAM 10 stopped while constructing `cellDisplacement`:

```text
inconsistent patch and patchField types for
patch type symmetryPlane and patchField type zeroGradient
.../0/cellDisplacement/boundaryField/lower
```

The point-motion repair correctly changed the `pointDisplacement` lower and
upper fields to `symmetryPlane`; however, the retained adapter auxiliary
`cellDisplacement` volVectorField still specified `zeroGradient` on those
same symmetry-plane mesh patches.  The corrected OpenFOAM 10 mover path reads
this field, so the mismatch is now exposed before time `0.005 s`.

The minimal future repair is restricted to making `cellDisplacement` lower and
upper patch-field types compatible with the actual symmetry-plane mesh patches,
then freezing a new contract and starting a new runtime.  This report does not
apply that change, re-run the 1 s case, or start Phase B.

## Required answers

1. Corrected fresh 1 s: **FAIL** before any committed coupled window.
2. Structure-to-mesh error: not evaluable; no mesh snapshot was produced.
3. Corrected 20 s: **not run**.
4. Corrected 20 s gate: **not completed**.
5. `max |y|/D`: not evaluable.
6. Fy RMS trends: not evaluable.
7. y RMS trends: not evaluable.
8. Raw force differentiation: not evaluable; no `forces.dat` was produced.
9. U/p differentiation: not evaluable.
10. Mean fluid power: not evaluable.
11. Cumulative fluid work: not evaluable.
12. 0.20 Hz evidence: not evaluable.
13. Numerical and ANCF quality: not evaluable; the CFD participants stopped
    during field construction and the structure participants were interrupted.
14. New bug: `cellDisplacement` symmetry-patch field mismatch.

`NEXT_LONG_DURATION_RUN = NOT_AUTHORIZED`.

The old 20 s and 370 s evidence remains unchanged and retains exactly the
limited disposition established before this task.
