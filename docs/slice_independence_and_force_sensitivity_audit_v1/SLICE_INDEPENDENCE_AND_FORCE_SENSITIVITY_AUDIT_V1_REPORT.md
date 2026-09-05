# SLICE_INDEPENDENCE_AND_FORCE_SENSITIVITY_AUDIT_V1

## Decision

`MOVING_MESH_NOT_APPLIED_BUG` is confirmed.  The immutable 20 s runtime used
three independent case directories, processes, force files, and preCICE
participant pairs.  Its CFD geometries nevertheless remained identical because
the fresh launcher set `namePointDisplacement unused` while its motion solver
was `displacementLaplacian`.  The adapter therefore retained distinct received
values in `cellDisplacement`, but did not project them to the
`pointDisplacement` field that moves mesh points.

The result is not a post-processing duplication, force-output path sharing,
preCICE channel alias, or forces-function-object patch-selection error.

## A. Immutable 20 s evidence

The source is read only:

`runtime/three_slice_physical_sanity_20s_v1_run_001`.

| Slice | case | fluid / structure participant | raw force file |
| --- | --- | --- | --- |
| 0 | `cases/slice_0000` | `Fluid_0000` / `Structure_0000` | `slice_0000/postProcessing/cylinderForces/0/forces.dat` |
| 1 | `cases/slice_0001` | `Fluid_0001` / `Structure_0001` | `slice_0001/postProcessing/cylinderForces/0/forces.dat` |
| 2 | `cases/slice_0002` | `Fluid_0002` / `Structure_0002` | `slice_0002/postProcessing/cylinderForces/0/forces.dat` |

Each case had an independent `pimpleFoam` process and an independent stdout
file.  The three absolute force paths differ.  The preCICE XML contains the
three distinct socket and exchange pairs `Structure_000i <-> Fluid_000i`;
`Displacement` flows structure-to-matching-fluid and `Force` in the reverse
direction.  No path or participant identity is shared where it must be unique.

The three 4,001-row raw `forces.dat` files are nevertheless byte-identical:

`83884c008c1558565c814dc64c46a8dfbd749a6fe75aeb201074bde197471fc4`.

At 0.005, 0.5, 1, 5, 10, 15, and 20 s, pressure, viscous, and total force
components agree exactly after independently parsing the three files.  The
maximum cross-slice `Fy` difference is exactly `0 N` in the raw file parser.

The Python evidence parser is not the cause: its synthetic three-file test
returns `Fy = 1, 2, 3` for `slice_0000..0002`, and its paths are verified unique.

## B. Actual geometry and field evidence

At 20 s `cellDisplacement` hashes differ, including their cylinder-boundary
values, but all three persisted `constant/polyMesh/points` files are identical
(`fbdbb5f...77149012f`).  No `20/polyMesh/points` and no
`20/pointDisplacement` evidence was written.  The original static cylinder has
40 faces, 80 points, area `3.138363834948743 m²`, and centroid `(0, 0, 0.5) m`.

More decisively, every `U` and `p` file at 5, 10, and 20 s is byte-identical
across all three cases.  Directly parsed, topology-indexed field differences
are zero in both L2 norm and every sampled value.  The samples at a near-wall
cell, a wake cell, and a far-field cell likewise coincide.  Thus the distinct
structural slice motions never became distinct CFD geometries or governing
equation states.

The force function object is correctly configured in all three cases:
`cylinderForces`, `patches (cylinder)`, `rho rhoInf`, `rhoInf 1000`, and
`CofR (0 0 0)` in the default region.  It is not integrating an external or
shared boundary.

The configuration-level synthetic preCICE routing probe writes structural
displacements `(+1, 0, -1) m` and receives exactly those values at
`Fluid_0000..0002`; reciprocal forces `(1, 2, 3) N` return to their matching
structure participants.  Together with the real distinct `cellDisplacement`
artifacts, this rejects channel aliasing.

## C. Repair and controlled sensitivity proof

The future fresh launcher now:

1. binds `namePointDisplacement pointDisplacement`;
2. retains `cellDisplacement` for the adapter face-centre field;
3. makes the `lower` and `upper` point patches `symmetryPlane` to match the
   actual mesh patches; and
4. supplies OpenFOAM 10's `cellDisplacementFinal` solver entry inside
   `fvSolution/solvers`.

The independent, uncoupled controlled test is:

`runtime/slice_force_sensitivity_controlled_v6`.

It ran for `0.1 s` with `dt=0.005 s`, using fixed cylinder offsets
`y=(0,+0.01,-0.01) m`.  It is a mesh/force sensitivity test, not a VIV result.
All three cases returned zero.

| offset y (m) | actual cylinder-centroid y at 0.1 s (m) | Fy at 0.1 s (N) |
| ---: | ---: | ---: |
| 0 | 0 | -9.9639080107936 |
| +0.01 | +0.01 | 68.840136350376 |
| -0.01 | -0.01 | -90.17097191838 |

All final mesh-point hashes differ.  The `U` L2 differences for pairs 0–1,
0–2, and 1–2 are `1.0371481635`, `0.9784263595`, and `1.9327962432`;
the corresponding `p` L2 differences are `0.5807418755`, `0.5510382735`, and
`1.0372576939`.  The maximum pairwise `Fy` difference is
`159.011108268756 N`.  Therefore the corrected path demonstrably performs:

`distinct point displacement -> distinct cylinder mesh -> distinct U/p -> distinct force`.

## D. Regression and disposition

Nine regression tests pass, including three-force parser independence,
three-path uniqueness, participant routing isolation, point-motion binding,
forces patch identity, controlled-sensitivity fail-closed gating, and the
existing slice-partition / OpenFOAM log parser tests.

`THREE_SLICE_PHYSICAL_SANITY_20S` remains a PASS only for its recorded
execution, force-contract, mapping, quality, Newton, and bounded-structure
evidence.  It is **not evaluable as moving-hydrodynamic or fluid-power
evidence**, because the CFD surface did not follow the three structural
motions.

`FRESH_20S_REVALIDATION = AUTHORIZED` after human approval only.  It must start
from a new runtime, retain all frozen physical and numerical contracts, and add
a hard per-step gate that requires a nonzero, slice-distinct
`pointDisplacement` / actual mesh-coordinate record whenever the structural
motions are distinct.  No 120 s calculation is authorized by this audit.

## Evidence files

- `results/slice_independence_and_force_sensitivity_audit_v1/slice_independence_audit.json`
- `results/slice_force_sensitivity_controlled_v6/controlled_sensitivity_gate.json`
- `results/slice_force_sensitivity_controlled_v6/controlled_sensitivity_mesh_and_field_audit.json`
