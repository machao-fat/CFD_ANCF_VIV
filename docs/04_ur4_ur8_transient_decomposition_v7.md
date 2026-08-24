# Ur=4 and Ur=8 transient decomposition v7

| point | fit interval (s) | response f (Hz) | f/fn | force f windows (Hz) | lambda fit/theory (1/s) | free/forced at tail end | fit residual | prediction residual | class |
|---:|---:|---:|---:|---|---:|---:|---:|---:|---|
| 4 | 90.00--140.00 | 0.175476 | 0.7019 | 0.173950/0.177002 | 0.117802/0.015708 | 0.0523% | 7.79% | 7.37% | asymptotically_periodic_outside_lockin |
| 8 | 111.25--240.00 | 0.159454 | 1.2756 | 0.160217/0.160217 | 0.0107088/0.00785398 | 12.0034% | 12.56% | 22.47% | outside_lockin_model_failed |

At 200 s the Ur=8 first-half prediction residual was 18.03%, so the run was extended from the existing 200 s checkpoint to 240 s under the unchanged safety limits. The final JSON records both the 200 s failed attempt and the extended result. The extended 240 s fit still fails the prediction residual gate (22.47% > 15%), so Ur=8 remains an explicit `outside_lockin_model_failed` result; no threshold was relaxed and no blind extension to 400 s was started.

The two points are reported as outside-lock-in only when the shared classifier passes all conditions; the label does not mean a strict raw single-frequency limit cycle.
