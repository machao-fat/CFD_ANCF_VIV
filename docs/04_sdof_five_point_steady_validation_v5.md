# Five-point SDOF steady validation v5

DFT is primary for response and lift frequency. Corrected zero crossing is diagnostic only. A point is not called lock-in from frequency synchronization alone; it must first pass the common late-window stationarity criteria. Low-power points use an absolute-power gate and are not automatically steady.

| Ur | final time (s) | strict steady | frequency state | physical class | max CFL | max |y| (m) |
|---:|---:|---|---|---|---:|---:|
| 4.0 | 130.0 | True | outside_frequency_sync | outside_lockin | 0.134102 | 0.0238134 |
| 5.2 | 112.0 | True | frequency_synchronized | transitional_or_unsteady | 0.180426 | 0.451883 |
| 6.0 | 150.0 | False | frequency_synchronized | transitional_or_unsteady | 0.151562 | 0.404686 |
| 7.1 | 142.0 | False | frequency_synchronized | transitional_or_unsteady | 0.175452 | 0.138153 |
| 8.0 | 160.0 | False | outside_frequency_sync | transitional_or_unsteady | 0.175452 | 0.0619743 |

Ur=5.2 window-shift status: `boundary_window_pass_only`, passing pairs `1/3`. The late 60--86/86--112 s pair passes, but the two earlier shifted pairs do not; therefore this is a boundary-window result rather than a robust stationarity result.

The old 8--34/34--60 s comparison remains startup-growth versus late response and is not used as a two-steady-window test.
