# FORMAL_IMPLICIT_PROJECTED_INITIAL_STATE_GUARD_CLOSURE_V1

## Scope

The sole authorized formal attempt is immutable at
`runtime/formal_implicit_projected_initial_state_guard_closure_v1_run_001`.
No 0.05 s or longer run was started.

## Projected initial-state contract

The full ANCF state is 102 DOF. `Structure-Mesh`/`Displacement` is a 2D x/y
interface. The corrected production payload is the existing mapping contract
projection `P_xy[r(q)-r_reference]`, in the same 40-vertex order used by
`write_data()`.

| slice | ux [m] | uy [m] | untransmitted uz [m] |
|---:|---:|---:|---:|
| 0 | 0 | 0 | 0.0132332091028786 |
| 1 | 0 | 0 | 0.0529515616443881 |
| 2 | 0 | 0 | 0.110292698472797 |

The minimal correction validates only the transmitted x/y payload against the
frozen `1e-12 m` zero-interface criterion. It does not alter q, uz, force
scaling, H/H-transpose mapping, or XML `initialize="yes"`.

The independent full-state validation remains: equilibrated marker, exact
frozen state SHA256, and finite q/qdot/qddot. Thus z is protected by full-state
provenance and is not forcibly zeroed.

## Regression and preflight

Real preCICE 3.4.1 regression PASS:
`results/formal_implicit_projected_initial_state_guard_closure_v1_regression_002/initial_data_and_path_regression.json`.

- legal nonzero untransmitted z: PASS;
- nonzero projected x/y, NaN/Inf, wrong dimension/count/order: fail closed;
- altered complete state: fail closed;
- required initial data are written before `initialize()` and received by the
  peer; omitted data fail closed;
- socket-path regression: PASS.

The existing authoritative launcher consumed that evidence before startup and
passed the three case, precursor, socket, adapter, checkpoint/wire/time-layer,
and containment preflights. The three Fluid cases loaded:

`/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib/libpreciceAdapterFunctionObject.so`

SHA256: `6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`.

## Formal one-window result

`FORMAL_IMPLICIT_PROJECTED_INITIAL_STATE_GUARD_CLOSURE_V1 = FAIL`.

The projected guard passed in production: all three Structure participants
wrote their 40-by-2 zero x/y payload before initialization, and all Fluid
participants connected and recorded `CHECKPOINT_WRITE` at OF time 0.100 s.

The unique first blocker was:

`FrameError: run_id is missing or too long`

The runtime ID `formal_implicit_projected_initial_state_guard_closure_v1_run_001`
is 64 characters. It failed while constructing the first C++ worker request.

- tentative iterations: 1; physical commits: 0;
- Structure, Fluid field/history, and mesh rollback: not evaluable; no restore
  occurred;
- final committed Fx/Fy and integrated structural forces: not available;
- uncommitted initialization force per slice: pressure
  `(631.472995517, -10.1496979812) N`, viscous
  `(718.725340208, 1.32682562818) N`, total
  `(1350.198335725, -8.82287235304) N`;
- Generalized Force V2 and Newton: not evaluable;
- Quality V4: not PASS for this uncommitted attempt; slice 0 p final residual
  was `0.00388440964083`, and slices 1--2 were stopped before complete evidence.

The next task must add a wire-safe IPC run-ID length preflight and a derived
short unique wire ID that preserves the full runtime ID in evidence. No
numerical or physical setting should change.

`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.
