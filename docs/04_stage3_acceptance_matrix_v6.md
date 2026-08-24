# Stage-3 v6 acceptance matrix

| Gate | Evidence | Result |
|---|---|:---:|
| response-cycle method and separate DFT/zero-crossing fields | `tests/sdof/analyze_response_cycle_aligned_v6.py`, v6 unit tests | PASS |
| Ur=5.2 robust late windows | 3/3 adjacent pairs pass | PASS |
| all five SDOF points steady | response-cycle final windows | FAIL |
| SDOF safety | max |y| < 1.5 m and CFL < 0.5 | PASS |
| EB/ANCF same-checkpoint online comparison | physical acceptance ready = True; common end time = True; mesh hash match = True; comparison = {"y_rms_relative_difference": 0.0012642175875599488, "y_peak_relative_difference": 0.0007116806055055985, "half_amplitude_relative_difference": 0.0007973052977244647, "frequency_relative_difference": 0.0, "fy_rms_relative_difference": 7.946875921176142e-05, "mean_power_relative_difference": 0.0010150552680290134} | PASS |
| dt/dt/2 sensitivity | inherited v5 short-window screen; long response-cycle convergence remains separate | CONDITIONAL |
| Python regression | 38 tests | PASS |
| MATLAB regression | inherited v5: 10/10 | PASS (inherited) |
| multi-slice claim | explicitly excluded | PASS |

**v6 decision:** CONDITIONALLY PASSED / NOT CLOSED.
