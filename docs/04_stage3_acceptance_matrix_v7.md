# Stage-3 v7 acceptance matrix

| gate | evidence | result |
|---|---|:---:|
| Ur=4 forced/free classification | v7 bounded fit, force/Cl stability, energy, safety | PASS |
| Ur=8 forced/free classification | v7 bounded fit, extension from 200 s checkpoint | FAIL |
| Ur=5.2/6/7.1 lock-in response-cycle evidence | v6 point metrics retained and reclassified only by shared results | PASS |
| SDOF safety | |y|<1.5D, CFL<0.5, finite | PASS |
| dt/dt/2 screening | 0--10 s, 0.9615-cycle scheme-B screen | PASS |
| formal long-window dt/dt/2 | same late state, 3--5 response cycles | OPEN |
| EB/ANCF common-window online comparison | v6 common measured-cycle boundaries | PASS |
| Python regression | v7 suite | PASS |
| MATLAB regression | 10/10, current v7 execution | PASS |
| multi-slice/full-riser claim | explicitly excluded | PASS |

## Decision

`stage3_fully_passed = False` and `eligible_for_stage4_prototype = False`. Blocking items: Ur8 asymptotic outside-lock-in classification failed: prediction residual gate remains open; dt/dt2 evidence is an existing 0-10 s, 0.9615-cycle scheme-B screening only; long-window scheme-A gate remains open.
