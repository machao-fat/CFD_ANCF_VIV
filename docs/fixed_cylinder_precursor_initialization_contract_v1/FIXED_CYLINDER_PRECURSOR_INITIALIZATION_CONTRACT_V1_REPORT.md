# FIXED_CYLINDER_PRECURSOR_INITIALIZATION_CONTRACT_V1

## Frozen scope

The formal precursor contract was written before its run at:
`runtime/fixed_cylinder_precursor_initialization_v1_run_002/fixed_cylinder_precursor_initialization_v1_contract.json`.
It freezes the original OpenFOAM 10 `pimpleFoam` geometry and mesh, `rho=1000 kg/m3`, `nu=0.01 m2/s`, `U=1 m/s`, `D=1 m`, `dt=0.005 s`, laminar Stokes model, original `fvSolution`, force patch `cylinder`, `rhoInf=1000`, and zero cylinder displacement/velocity.  Neither preCICE nor the ANCF worker was started.

The initial 0.02 s probe was insufficient to pre-register a terminal-variation test, so a separately labelled 0.1 s fixed-cylinder characterization was run first.  It established a 20-step cold-start decay history; it is not a precursor state.

The resulting formal precursor duration was frozen at `0.100 s`.  With `F_ref = 0.5 rho U^2 D span = 500 N`, startup-balanced requires, over the last four formal precursor points: terminal `|Fx| <= 5000 N` and every successive `Fx` change `<=50 N`.  These are an impulse-removal test only, not a developed-wake or stationarity claim.

## Formal precursor

The static precursor completed 20/20 steps and OpenFOAM Quality V2 passed (maximum Courant `0.350855773225`, maximum absolute global continuity `1.10665568732e-08`, and terminal Ux/Uy/p residuals below `1e-8`).

At `t=0.100 s` its cylinder force was:

| component | Fx [N] |
|---|---:|
| pressure | `631.4729955170` |
| viscous | `718.7253402086` |
| total | `1350.1983357256` |

The last-four-point maximum successive variation was `40.2321052284 N`, so `PRECURSOR_STARTUP_BALANCED = pass`.  The terminal value is `2.70 F_ref`, versus the cold-start `309.7 F_ref` pressure impulse, and therefore does not retain the cold-start impulse.

`U`, `p`, and `phi` at `t=0.1` were exported with SHA-256 identities as `PRECURSOR_STATE_V1`.  `Uf` and `meshPhi` do not exist in a fixed-mesh precursor and were not fabricated: OpenFOAM 10 reconstructs `Uf` from `U` on dynamic startup; a zero-motion mesh update reconstructs `meshPhi`, which was observed as exactly zero at the first dynamic continuation time.

## Transfer strategy and independent restarts

Strategy A was used: retain physical OpenFOAM time, from `0.100` to `0.120 s`.  No reset to coupled `t=0` was attempted or claimed.  Thus a reset-consistency result is `not_applicable`, not pass.

Both branches started with byte-identical exported `U/p/phi` hashes.

| branch | first advanced time | Fx pressure [N] | Fx viscous [N] | Fx total [N] | jump from terminal [N] |
|---|---:|---:|---:|---:|---:|
| fixed restart | 0.105 s | 617.8348315049 | 702.6430909763 | 1320.4779224812 | 29.7204132444 |
| zero-motion dynamic restart | 0.105 s | 542.6167070165 | 705.5872173784 | 1248.2039243949 | 101.9944113307 |

The frozen restart-jump limit is `100 N`.  Therefore `FIXED_RESTART_CONTINUITY = pass`, but `ZERO_MOTION_DYNAMIC_RESTART_CONTINUITY = fail` by `1.9944113307 N`.  The fixed/dynamic first-advanced force difference is `72.2739980863 N`, below its separate `100 N` branch-difference limit.  Neither restart recreates an `O(1e5 N)` pressure impulse.

The dynamic branch persisted `Uf` at `t=0.105 s` and its `meshPhi` internal field is zero.  Its contracted Ux/Uy/p terminal residuals, Courant, and continuity subgates pass.  However, the literal frozen Quality V2 evaluator also treats zero-iteration `cellDisplacementx/y` motion solves and `pcorr` as uncontracted linear-fluid solves, so its aggregate status is fail.  That parser-coverage issue is recorded but not modified or reclassified in this task.

Thus `FIELD_TRANSFER_CONSISTENCY = fail` at the complete gate level, despite exact initial U/p/phi transfer and successful deterministic Uf/meshPhi reconstruction.

## Negative control and structural boundary

The preserved cold-start characterization reproduces `Fx(0.005 s)=154850.737753531 N`; `COLD_START_REGRESSION = pass`.

The terminal precursor total gives a hypothetical future structural slice load of `1350.1983357256 * 16.666666666666668 = 22503.3055954267 N`.  It is intentionally not sent to ANCF here.  `STRUCTURAL_MEAN_LOAD_INITIALIZATION = not_completed`: the current ANCF initial state has not been recomputed as static equilibrium under this nonzero mean drag, and this CFD precursor contract does not change structural `q0`, `qdot0`, damping, or physics.

## Gate result

| gate | result |
|---|---|
| PRECURSOR_CONTRACT | pass |
| PRECURSOR_STARTUP_BALANCED | pass |
| PRECURSOR_STATE_EXPORT | pass |
| FIXED_RESTART_CONTINUITY | pass |
| ZERO_MOTION_DYNAMIC_RESTART_CONTINUITY | fail |
| FIELD_TRANSFER_CONSISTENCY | fail |
| COLD_START_REGRESSION | pass |
| STRUCTURAL_MEAN_LOAD_INITIALIZATION | not_completed |

`NEXT_COUPLED_0P1S = NOT_AUTHORIZED`.  No coupled smoke was launched.
