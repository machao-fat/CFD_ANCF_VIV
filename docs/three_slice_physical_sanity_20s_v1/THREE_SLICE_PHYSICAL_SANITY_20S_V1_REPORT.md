# Three-slice physical sanity 20 s V1

## Result

`THREE_SLICE_PHYSICAL_SANITY_20S = PASS` for bounded execution and frozen
force/mapping/quality contracts. This is not a VIV, lock-in, or convergence
claim. Formal VIV, lock-in, amplitude and frequency statuses remain
`not_evaluated`.

## Execution and response

Fresh execution completed 4,000/4,000 windows from `t=0` to `20 s`; all six
participants returned zero. Each slice has 4,000 force records. Newton evidence
contains 4,000 predictions and 4,000 corrections.

| Slice | max `|y|/D` | Fy RMS early/mid/late (N) | y RMS early/mid/late (m) |
| --- | ---: | --- | --- |
| 0 | 0.00320830 | 203.050 / 54.106 / 125.224 | 0.001256 / 0.001132 / 0.001594 |
| 1 | 0.00543175 | 203.050 / 54.106 / 125.224 | 0.002043 / 0.001873 / 0.002596 |
| 2 | 0.00237070 | 203.050 / 54.106 / 125.224 | 0.000929 / 0.000827 / 0.001178 |

All responses are finite, below the pre-run 7.5 m guard, and classified
`BOUNDED`; stationarity is not claimed.

## Exploratory frequencies

Modal projection is `not_available`. The 0.198761 Hz single-frequency response
projection is 58–61% of the strongest coarse-grid response, whose grid peak is
0.15 Hz. First-mode evidence is therefore **weak**. Force and displacement
coarse-grid peaks are near 0.15 Hz; force zero-crossing estimates contain about
13 cycles near 0.796 Hz, showing faster force variation. All frequency evidence
is exploratory. `Delta f = 1/20 = 0.05 Hz`; the 0.16 versus 0.20 Hz question is
**insufficient_duration** for a formal conclusion.

## Power and energy

| Slice | mean Fy*vy (W) | cumulative Fy*vy work (J) |
| --- | ---: | ---: |
| 0 | 0.0204530 | 0.409061 |
| 1 | 0.0352936 | 0.705872 |
| 2 | 0.0141180 | 0.282359 |

Total mean power is 0.0698646 W and total work is +1.39729 J. Thus cross-flow
fluid work is positive. Structural mechanical energy is
`not_available_from_current_C++_wire`, so work-to-energy closure is not
evaluable. With zero damping and weak modal evidence, persistent startup free
mode is **possible**, not established as principal.

## Quality and contracts

No instability or restart jump was found. OpenFOAM Quality V2 passes in all
slices: max Courant 0.350855773225, max global continuity 1.10665568732e-8,
and terminal maxima `p=9.99879755524e-9`, `Ux=9.99659849617e-9`,
`Uy=9.95566809245e-9`. Mapping/force results pass: max force error
1.4551915228366852e-11 N, absolute moment error 2.9802322387695312e-8 Nm,
V2 moment error 3.03421564111264e-16, virtual-work error 7.99360577730113e-15.

## Local-force sensitivity anomaly

Slice displacements differ by as much as 0.00306479 m, and final
`cellDisplacement`/cylinder boundary values differ across cases. Yet integrated
`Fy(t)` is identical across all three cases to within 2.73e-12 N. This is an
unresolved moving-mesh/hydrodynamic-load sensitivity anomaly.

`NEXT_LONGER_PHYSICAL_RUN = NOT_AUTHORIZED` until it is diagnosed. After repair
and revalidation, a fresh minimum 120 s diagnostic would yield
`Delta f about 0.0083 Hz` and roughly 19–24 cycles near 0.16–0.20 Hz; it still
requires explicit approval.
