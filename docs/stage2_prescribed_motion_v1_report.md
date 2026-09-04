# Stage 2 Prescribed-Motion Cross-Solver Verification

## Current gate

`STAGE2_PRESCRIBED_MOTION_PREFLIGHT_V1_GATE` is
`OPEN_WITH_FLUENT_V2_REPAIR_PENDING`. The OpenFOAM 10 one-second
prescribed-motion smoke and Fluent mesh import/check passed. Fluent UDF
compilation passed; v2 dynamic-mesh setup and the Fluent transient smoke remain
pending.

The first Fluent transient attempt advanced through 189 steps, then fail-closed
at `t=0.4724996388 s` because one non-positive-volume cell was detected. This
is a dynamic-mesh configuration failure, not a cross-solver comparison result.
The v2 repair uses smoothing plus local remeshing in a single deforming fluid
zone and retains every physical/numerical contract parameter. A separate
two-cell-zone Gmsh mesh was generated only as an offline topology exploration;
it is not used by v2 because a shared-node zone boundary cannot represent the
required relative motion.

## Frozen contract

Single cylinder, no ANCF feedback and no preCICE; `D=1 m`, `U=1 m/s`,
`rho=1 kg/m3`, `nu=0.01 m2/s` (`Re=100`), `A=0.10 m`, `f=0.16 Hz`,
`dt=0.0025 s`, one-second smoke. The motion is analytic external
`y(t)=0.10 sin(2 pi 0.16 t)`.

## Evidence

- Gmsh source geometry was converted to an OpenFOAM 10 mesh and passed
  `checkMesh` (3408 points, 3268 cells, max non-orthogonality 21.66 degrees,
  max skewness 0.451).
- OpenFOAM transient smoke completed 400 steps in approximately 3.44 wall s;
  maximum Courant was approximately 0.158 and cumulative continuity error was
  approximately `1.74e-8`.
- `foamMeshToFluent` exported a Fluent mesh. Fluent 2023 R2 read it in 3D mode
  and `/mesh/check` passed with the same domain extents, nodes and cells.
- Fluent compiled the `stage2_cylinder_motion` UDF for both 3ddp host and node
  libraries (`libudf.dll`, return code 0). The compiler emitted only the
  parallel-session and missing Visual Studio detection warnings.
- Earlier attempts to import Gmsh directly were rejected; those were setup
  probes only and did not run a transient solve.

## Remaining work

Hook `stage2_cylinder_motion` as the cylinder dynamic-mesh motion, set the
fluid properties and boundary conditions, add force monitors, and run the
authorized one-second Fluent smoke. Only after that result is complete can
the OpenFOAM/Fluent load, RMS, phase and lag comparison gate be evaluated.

The 370-second ANCF trajectory is not used as the formal Stage 2 input.
Formal Strouhal, stable-response and lock-in statuses remain unchanged.
