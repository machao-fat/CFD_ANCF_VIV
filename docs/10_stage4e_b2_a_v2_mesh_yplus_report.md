# Stage 4E-B2-A-v2: mesh, yPlus and CFL audit

The final evidence run is `20260814T154500000Z_stage4e_b2_a_v2_registryfix`. It uses a fresh, x-mirror-symmetric eight-sector attached O-grid-equivalent topology with coarse/medium/fine in-plane counts `12/16/24`, radial grading `6/100/1000`, and `z/D=[-0.5,0.5]`.

All six short cases completed `blockMesh`, `checkMesh`, `setFields` and `pimpleFoam` with return code 0, `End`, and finite logs. Their measured maximum CFL values were `0.4531`, `0.4266`, and `0.4360` for the coarse, medium and fine families. Independent cylinder-patch yPlus p95 values were:

| model | coarse | medium | fine |
|---|---:|---:|---:|
| laminar | 15.4941 | 4.2632 | 0.4969 |
| kOmegaSST | 5.4687 | 0.4286 | 0.000683 |

The fine SST precheck therefore satisfies the diagnostic p95 y+ <= 1 condition. This is not a completed SST model Gate because the formal statistical window was stopped before model/mesh convergence.

The formal high-laminar-medium run used `dt=4e-4 s`, `endTime=5.5 s`, and reached the requested physical end with `End`, but its history contained `max CFL=1.706483721948689`; the hard stop is `CFL >= 0.8` and the formal target is `<=0.5`. Consequently the v2 pilot stopped at this condition and did not start formal SST, mesh, timestep, domain or low/middle/high cases.

The independent measured geometry, yPlus, CFL, log and process records are in the run-specific result and runtime directories.
