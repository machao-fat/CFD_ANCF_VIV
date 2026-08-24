# Stage 3 acceptance matrix v5

| Gate | Status | Evidence |
|---|---|---|
| Frequency fix and unit tests | PASS | 31/31 Python tests |
| Ur=5.2 robust shifted-window stationarity | BLOCKED | 1/3 pairs |
| Five-point common late-window criterion | BLOCKED | five_point_v5_completed_with_stationarity_states |
| EB/ANCF long online physical comparison | BLOCKED | long_time_online_comparison_completed_but_acceptance_incomplete |
| MATLAB structure regression | PASS | 10/10 |
| dt/dt/2 screen | PASS | inherited v4 evidence; no long-window overclaim |
| Scope boundary | PASS | No multi-slice claim |

Overall: `stage3_fully_passed=false`.
