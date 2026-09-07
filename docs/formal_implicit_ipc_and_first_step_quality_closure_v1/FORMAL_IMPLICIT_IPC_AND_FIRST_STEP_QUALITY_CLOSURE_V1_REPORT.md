# FORMAL_IMPLICIT_IPC_AND_FIRST_STEP_QUALITY_CLOSURE_V1

## Decision

`FORMAL_IMPLICIT_IPC_AND_FIRST_STEP_QUALITY_CLOSURE_V1 = PASS` by the read-only
re-audit of the one permitted fresh production window.  The original immutable
`FORMAL_IMPLICIT_ONE_WINDOW = FAIL` artifact is retained unchanged: it used a
parser that could not represent two completed implicit trials at the same
OpenFOAM physical time.

`NEXT_IMPLICIT_0P05S = AUTHORIZED`; this task did **not** launch it.

## IPC identity closure

The first previous attempt supplied the human runtime name
`formal_implicit_projected_initial_state_guard_closure_v1_run_001` as
`run_id`.  Its UTF-8 length was exactly 64.  Both Python and C++ reserve
`ID_RUN = 64` bytes for a NUL-terminated C string, hence the legal range is
1--63 UTF-8 bytes.  The Python encoder rejected the frame before prediction.

The versioned `cfd-ancf-ipc-identity-contract-v1` separates:

- human runtime name and runtime path (metadata only);
- human case name (metadata only);
- a stable ASCII wire `run_id` / `case_id`: `r1-` / `c1-` plus 60 hexadecimal
  SHA-256 characters (63 bytes total);
- non-restorable monotonic wire request/transaction/attempt identity; and
- restorable physical-window identity.

The collision policy is fail-closed against a persisted ledger mapping the
same derived ID to a different full name.  It never uses a runtime path as a
wire ID.

`IPC_IDENTITY_CONTRACT_V1 = PASS` in
`results/formal_implicit_ipc_and_first_step_quality_closure_v1_ipc_regression_004`:
short and exact-63-byte IDs encoded; 64-byte, empty, control-character, and
UTF-8-byte-overflow IDs failed closed.  The real C++ worker then completed the
six restore/retry cycles with 12 unique wire sequences and deterministic
prediction/correction responses.

## Quality V4 audit

The raw failure line in immutable runtime
`formal_implicit_projected_initial_state_guard_closure_v1_run_001` was:

| Item | Value |
|---|---:|
| slice | 0 |
| OF time | 0.105 s |
| tentative iteration | first only; runtime was stopped by IPC failure |
| PIMPLE outer corrector | 1 |
| equation | `p` / GAMG |
| initial residual | 0.702852115927 |
| recorded final residual | 0.00388440964083 |

That line was not terminal: the IPC failure terminated the participant before
the next pressure correction and `ExecutionTime`.  The exact zero-motion,
no-ANCF CFD-only reproduction retained the same settings and state, executed
the following p correction, and ended at `5.63496486627e-09` after 17
iterations.  It passed V4.

The parser now records `physical_timestep_completed` only after OpenFOAM's
`ExecutionTime` line.  An incomplete record is still fail-closed, but its
last p solve is not mislabeled as terminal.  It also accepts an equal OF time
only when the prior record completed: this is the expected signature of a
parallel-implicit rollback trial.  The regression covers both a truncated
log and two completed trials at OF `0.105 s`.

The current one-window raw logs contain two completed trials at the same OF
time for all three slices.  Re-audit with parser 1.0.3 yields `Quality V4 =
PASS` for all slices.  There is no real first-step numerical quality failure
under the frozen V4 residual limits.

## Production preflight and one-window evidence

The centralized launcher preflight passed projected initial-state data,
socket canonicalization, IPC identity/boundary regression, adapter identity,
patch-0005 build manifest, moving-mesh case contract, precursor hashes,
checkpoint/wire regression, time-layer contract, containment, and the V4
completion regression.

The one authorized formal window used:

- parallel-implicit, dt = 0.005 s, fixed-point min/max = 2/8;
- coupling time `0 -> 0.005 s`; OF time `0.100 -> 0.105 s`;
- `NO_FLOW_EQUILIBRIUM`, `PRECURSOR_STATE_V1`, and the patch-0005 adapter;
- actual adapter SHA256 `6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`.

It ran two coupling iterations and committed one physical window.  For each
slice, the Fluid trace contains `CHECKPOINT_WRITE`, `PRE_ROLLBACK_TRIAL`,
`POST_ROLLBACK_BEFORE_NEXT_INPUT`, and `FINAL_COMMIT`; field/history and
dynamic-mesh rollback identities are PASS.  Structure rollback is PASS and
wire sequences are monotonic (1, 2, 3, 4).

Final raw force per slice was pressure `(542.6167070165, -47.2938883278) N`,
viscous `(705.5872173784, 1.328101890468) N`, and total
`(1248.2039243949, -45.965786437332) N` for `(Fx, Fy)`.  The corresponding
integrated slice force was `(20803.3987399146, -766.0964406221, 0) N`.

Force contract, Generalized Force Metric V2, ANCF Newton, mesh tracking and
mesh rollback all passed; there was no FPE or negative cell.  The original
gate artifact remains immutable with its old parser result.  The separately
stored read-only re-audit is the decision evidence.

## Evidence and commits

- IPC regression: `results/formal_implicit_ipc_and_first_step_quality_closure_v1_ipc_regression_004/ipc_contract_regression.json`
- CFD-only reproduction: `results/formal_implicit_ipc_quality_cfd_only_reproduction_v1_run_002/cfd_only_quality_reproduction.json`
- Quality completion regression: `results/formal_implicit_ipc_quality_v4_completion_regression_002/quality_v4_completion_regression.json`
- Formal runtime: `runtime/formal_implicit_ipc_and_first_step_quality_closure_v1_run_001`
- Formal read-only re-audit: `results/formal_implicit_ipc_and_first_step_quality_closure_v1_reaudit_001/formal_window_quality_v4_reaudit.json`

Commits:

- `23d9953 fix: validate IPC identity and completed OpenFOAM time steps`
- `36c364a validation: classify only completed OpenFOAM time steps as terminal`
- `68fe3bc validation: audit implicit trial time records without terminal aliasing`
