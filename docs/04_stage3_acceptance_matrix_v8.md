# Stage-3 v8 acceptance matrix

| gate | result |
|---|:---:|
| Ur=4 | asymptotically_periodic_outside_lockin | PASS |
| Ur=5.2 | locked_or_near_lockin | PASS |
| Ur=6 | locked_or_near_lockin | PASS |
| Ur=7.1 | locked_or_near_lockin | PASS |
| Ur=8 | asymptotically_periodic_outside_lockin | PASS |
| Ur=5.2 common-checkpoint dt/dt2 long window | PASS |
| EB/ANCF long online comparison | PASS |
| Python v8 regression | PASS |
| MATLAB v8 regression | PASS |
| v8 figure source QA (FAIL count) | PASS |
| CFL/mesh/finite/restart/safety | PASS |
| multi-slice/full-riser claim | explicitly excluded |

`stage3_fully_passed = True`; `eligible_for_stage4_prototype = True`.
Blocking items: none.
