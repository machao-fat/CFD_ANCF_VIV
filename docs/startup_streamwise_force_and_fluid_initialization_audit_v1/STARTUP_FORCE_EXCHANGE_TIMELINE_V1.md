# Startup force-exchange timeline V1

Source run: `generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001` (immutable).
The first correction is global step 1, tick `5000000`, physical time `0.005 s`.

| Sequence | Owner | Physical time | Evidence | Quantity / result |
|---|---|---:|---|---|
| 0 | OpenFOAM / preCICE | 0 | `fluid_0000.stdout` | `Force` and `Displacement` mappings at `t=0` are explicitly logged as skipped zero samples. |
| 1 | C++ ANCF | 0.005 | `records.jsonl`, prediction | Prediction 1 returns zero interface `ux`, `uy`; the reference-coordinate `uz` is not transmitted to the 2-D fluid participant. |
| 2 | Structure participant | 0.005 | `structure_participant.py:132` | The participant writes `[ux, uy]` as `Displacement` on each Structure-Mesh. |
| 3 | preCICE / fluid | 0.005 window | `fluid_0000.stdout` | The fluid consumes the zero displacement and advances its first fluid step. |
| 4 | OpenFOAM | 0.005 | probe and fluid log | It solves the cold-start flow field and evaluates the cylinder `forces` object. |
| 5 | Fluid participant | 0.005 | `fluid_0000.stdout:107` | preCICE maps `Force` for `t=0.005` from Fluid-Mesh to Structure-Mesh. |
| 6 | Structure participant | 0.005 | `structure_participant.py:133-139` | It returns from `advance(0.005)`, reads `Force` with relative read time `0.0`, sums the 40 mapped vertex values, and creates `LoadRecord` as raw OpenFOAM force [N]. |
| 7 | Force contract | 0.005 | `records.jsonl` | With span `1 m` and tributary length `16.666666666666668 m`, raw `Fx=155312.54389220272 N` becomes line force `155312.54389220272 N/m`, then `Fx_slice=2588542.398203379 N`. |
| 8 | C++ ANCF | 0.005 | correction 1 | The formal `H^T` mapping consumes integrated slice force [N] and completes correction 1. |

Conclusion: correction 1 uses a freshly computed `t=0.005 s` fluid force; it does not consume a `t=0` initial, stale, or default preCICE force.
