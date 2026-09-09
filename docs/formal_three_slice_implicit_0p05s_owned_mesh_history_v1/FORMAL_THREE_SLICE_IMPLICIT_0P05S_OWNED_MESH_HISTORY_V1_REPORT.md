# FORMAL_THREE_SLICE_IMPLICIT_0P05S_OWNED_MESH_HISTORY_V1

## Decision

`IMPLICIT_0P05S = FAIL_CLOSED`.

This was the one authorized three-slice ANCF-CFD run. It was not retried,
extended, or numerically modified. The first runtime blocker was a frozen
containment breach at physical window 10, tentative iteration 3, at
`t_OF=0.150 s`:

| slice | raw Fx | frozen limit |
| ---: | ---: | ---: |
| 0 | `-2083602.4229046283 N` | `2000000 N` |
| 2 | `-2084484.997346848 N` | `2000000 N` |

The structure participant stopped fail-closed before committing that window.
No later explicit regression or longer case was started.

## Frozen production identity and preflight

Runtime: `runtime/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001`.
The selected adapter is the accepted owner-observability candidate,
SHA256 `c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17`,
with the frozen point-vector reset semantics. The worker SHA256 is
`cb0e63116ede3c17d79e256eb1833edcdff8574d178ac1bfc81d2bcc2fad0d06`.
The isolated Foundation OF10 ABI preflight passed; libOpenFOAM,
libfiniteVolume, motion libraries, pimpleFoam and the adapter resolved from
the selected prefix. Initial-data, projected guard, socket, IPC, precursor,
moving-mesh case, and frozen containment preflights passed.

The run used production `parallel-implicit`, `dt=0.005 s`, `min/max=2/8`, no
acceleration, the frozen NO_FLOW_EQUILIBRIUM state, and OF `0.100 -> 0.150 s`.

## Runtime completion

All three fluid traces show 10 checkpoint writes, 19 restore events, and 10
`FINAL_COMMIT` events at `t_OF=0.150 s`; however the tenth structure window
was not committed. The authoritative structure record contains 9 committed
windows through `t_OF=0.145 s`, 29 ANCF transport iterations, and the error
`RuntimeError: frozen realtime containment threshold crossed`.

Committed coupling iterations were 3 for each of windows 1--9. Wire identity
remained unique and monotonic. No IPC disconnect or FPE was observed.

## Forces and response through the last committed window

| slice | max |raw Fx| | max |raw Fy| | max |ux| | max |uy| | max |vx| | max |vy| |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | `806313.3384 N` | `51427.8109 N` | `0.003219707 m` | `0.000179111 m` | `2.231194 m/s` | `0.145169 m/s` |
| 1 | `566098.4773 N` | `36106.4463 N` | `0.002109057 m` | `0.000103456 m` | `1.316452 m/s` | `0.085230 m/s` |
| 2 | `806609.5936 N` | `51445.8414 N` | `0.003218530 m` | `0.000179182 m` | `2.232253 m/s` | `0.145248 m/s` |

Last committed (`tau=0.045 s`, `t_OF=0.145 s`) integrated streamwise forces
were `13438555.6397`, `9434974.6222`, and `13443493.2264 N` for slices 0--2.
There is no final committed force for the rejected tenth window.

## Quality, algebra, and rollback status

Generalized Force V2, Force Contract, and the Newton evidence produced by the
completed records passed for the accepted portion. The run-level Newton gate
is not PASS because the tenth window terminated before a complete record.

Quality V4 is `FAIL` for all slices on the real hard condition `Courant quality
failure`; maximum Co was `1.46356946867` (slice 0), `1.14257187046` (slice 1),
and `1.46400134025` (slice 2), above the frozen 0.5 limit. PIMPLE terminal
convergence passed where parsed; mesh auxiliary high-iteration messages are
warnings, not the first blocker.

The corrected auditor now reads owner-private `old_points` and owner-owned
`meshPhi` schema paths. Its versioned U/Uf lazy contract accepts only the
generation-1 zero-history `0 -> 1` transition. Generation 2 has persistent
oldTime levels but the runtime trace contains no old-time value fingerprints,
so that portion remains `PERSISTENT_HISTORY_NOT_OBSERVABLE` and fails
closed. This is an independent qualification gap, not reclassified as a
solver failure and not repaired after the run.

The raw versioned audit is retained at
`results/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001/versioned_rollback_audit.json`.
The containment event, traces, logs, and gate JSON remain immutable under the
new runtime. The original two-window `FAIL` and old auditor records remain
unchanged.

Read-only final-state `checkMesh -time 0.15 -allTopology -allGeometry` returned
`Mesh OK` for all three fluid cases. The minimum volumes were
`0.00161187777359`, `0.00160480881820`, and `0.00161188593849`; maximum
non-orthogonality was `30.6535934622`, `30.6485339779`, and `30.6536015544`;
maximum skewness was `0.503077454543`, `0.503079398538`, and `0.503077452783`.
This geometry result does not override the failed coupling/containment gate.

## Scope conclusion

This result does not establish VIV, lock-in, long-time stability, or an
algorithmic advantage. It is a bounded numerical failure after 9 committed
windows, with the first blocker identified and preserved.

```
IMPLICIT_0P05S = FAIL_CLOSED
FIRST_BLOCKER = FROZEN_CONTAINMENT_BREACH_RAW_FX_WINDOW_10_ITERATION_3
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```
