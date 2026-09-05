# MOVING_MESH_PATCH_CONSISTENCY_FIX_AND_1S_RETRY_V1 report

## Decision

`CORRECTED_COUPLED_1S_SMOKE = FAIL`.

The original OpenFOAM boundary-field blocker is fixed for future generated cases.  The fresh runtime passed the three-slice mesh-field compatibility preflight and all three OpenFOAM participants constructed and advanced their dynamic-mesh solves.  It then failed closed after 9 committed coupled windows because the structure process raised `RuntimeError: C++ generalized force differs from formal H^T mapping`.  No retry of this runtime and no 20 s run was performed.

## A. Authoritative patch fix

The authoritative generator is `tools/three_slice_force_contract_smoke_v1/run_smoke.py`, field template `CELL`.  It now generates these boundary fields:

| Item | lower | upper |
| --- | --- | --- |
| `constant/polyMesh/boundary` | `symmetryPlane` | `symmetryPlane` |
| `0/pointDisplacement` | `symmetryPlane` | `symmetryPlane` |
| `0/cellDisplacement` | `symmetryPlane` | `symmetryPlane` |

The historical failed runtime `runtime/corrected_moving_mesh_1s_run_001` was not edited.

## B. Boundary compatibility and construction preflight

The compatibility preflight read the real `constant/polyMesh/boundary` and the motion fields selected by the generated `dynamicMeshDict` and `preciceDict`, rather than assuming fields from filenames.  For each of `slice_0000`, `slice_0001`, and `slice_0002`, required fields were `pointDisplacement` and `cellDisplacement`; both inventories were compatible and no issue was reported.

`MESH_FIELD_PATCH_COMPATIBILITY = PASS` for all three slices.  No other generated patch-field incompatibility was found.

The static construction preflight passed before time advancement.  The subsequent actual launch supplies additional evidence that this was not merely a text check: all three OpenFOAM logs show dynamic-mesh displacement solves and reach `Time = 0.055 s`; the prior `symmetryPlane` / `zeroGradient` construction error did not recur.

## C. Fresh runtime disposition

Runtime: `runtime/moving_mesh_patch_consistency_1s_retry_v1_run_001`.

- Expected coupled windows: 200.
- Committed coupled windows: 9.
- Structure process failed during correction for step 10 at `t = 0.050 s`.
- Fluid processes were then terminated by the coordinated launcher (exit 143); they reached log time `0.055 s`.
- The C++ worker itself returned code 0, but the structural adapter fail-closed mapping audit raised `C++ generalized force differs from formal H^T mapping`.
- Newton evidence is `FAIL/not complete` because the abort left the expected prediction/correction record count incomplete.

This is a new, non-boundary, H/H^T mapping consistency blocker.  It must be diagnosed in a separate authorized task before another fresh 1 s retry.

## D. Moving-mesh, field, and force evidence limits

The abort occurred before the first required `0.1 s` mesh snapshot.  Therefore max structure-to-actual-mesh tracking error, cross-slice actual-cylinder geometry independence, and saved U/p field differences are `not evaluable` for this failed runtime.  The only written `forces.dat` record is the shared initial `t = 0` line, so raw-force differentiation is also `not evaluable`; equal initial force output is not evidence of a repeated hydrodynamic-force bug.

The log-only Courant values rose as high as 7.10 by the abort, but the run is incomplete and Quality Contract V2 therefore has no PASS result.  This observation is not used to alter the frozen numerical contract or as the primary blocker.

## E. Gate summary

| Gate | Result |
| --- | --- |
| MESH_FIELD_PATCH_COMPATIBILITY | PASS |
| OpenFOAM field/dynamic-mesh construction | PASS |
| 200 committed windows | FAIL, 9/200 |
| Force/mapping contract | FAIL, C++ generalized-force mismatch |
| Moving-mesh application evidence | NOT_EVALUABLE |
| Slice geometry independence | NOT_EVALUABLE |
| OpenFOAM Numerical Quality V2 | NOT_EVALUABLE |
| ANCF Newton evidence | FAIL/not complete |
| FRESH_CORRECTED_20S | NOT_AUTHORIZED |

## Next action

The unique minimal blocker is the C++ generalized-force-versus-formal-H^T mapping mismatch observed at the first uncommitted correction.  Preserve this runtime and diagnose that mapping evidence before any fresh retry.  Do not change physical parameters, numerical settings, or the frozen contracts to bypass it.
