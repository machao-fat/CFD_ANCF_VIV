# IMPLICIT_MOVING_MESH_CASE_CONTRACT_FIX_AND_ONE_WINDOW_REQUALIFICATION_V1_REPORT

## Generator root cause and repair

The common launcher function previously added only `cellDisplacementFinal` and inherited it from `cellMotionUx`.  It never created the ordinary `cellDisplacement` entry required by the deployed OpenFOAM 10 `displacementLaplacian` path.  The previous one-window runtime therefore failed before a valid fluid trial.

The authoritative contract is [moving_mesh_openfoam10_case_contract_v1.py](../../src/coupling/moving_mesh_openfoam10_case_contract_v1.py).  It requires the `pointDisplacement` and `cellDisplacement` fields; `namePointDisplacement pointDisplacement` and `nameCellDisplacement cellDisplacement` bindings; a `displacementLaplacian` mover; and both `cellDisplacement` and `cellDisplacementFinal` fvSolution entries.  The ordinary entry inherits frozen `cellMotionUx` settings (`PCG`, `DIC`, tolerance `1e-8`, `relTol 0`); Final retains the same validated `cellMotionUx` inheritance with `relTol 0`.

The four generator outputs pass the shared contract preflight.  Four synthetic invalid cases (missing ordinary entry, missing Final entry, incompatible symmetry field patch, and wrong point binding) each failed closed.  The fresh no-preCICE three-slice construction probe passed and called the ordinary `cellDisplacementx/y` solve; no undefined-keyword or patch mismatch occurred.

## Fresh one-window requalification

- Runtime: `runtime/implicit_one_window_requal_v1_run_001` (immutable).
- Configuration: parallel-implicit, `dt=0.005 s`, one physical window, two fixed-point iterations, no acceleration.
- All three structure/fluid processes returned `0`.
- Structure checkpoint write/read passed; physical state hash restored exactly.
- C++ wire sequences were `1, 2, 3, 4`, unique and monotonic.
- One physical window committed once: coupling time `0 → 0.005 s`; OpenFOAM `0.100 → 0.105 s`.
- Each fluid log records exactly two tentative solves at `Time = 0.105s`, proving the rollback iteration did not accumulate OpenFOAM physical time.
- Final raw force per slice: pressure `542.616707016 N`, viscous `705.587217378 N`, total `1248.203924394 N`.
- OpenFOAM Quality V4 passed for each final committed trial. Generalized Force Metric V2 passed on both trial corrections.

## Strict rollback disposition

The deployed OpenFOAM adapter did execute the second same-window iteration, but it does not expose checkpoint-time snapshots/hashes of `U`, `p`, `phi`, `Uf`, `meshPhi`, point/cell displacement, or mesh points.  Direct field and geometry restoration therefore remain `NOT_EVALUABLE`; two same-time solves are not substituted for the requested hash/numerical-identity proof.

Consequently:

- `OPENFOAM_ROLLBACK = OBSERVED_BUT_FIELD_IDENTITY_NOT_EVALUABLE`
- `DYNAMIC_MESH_ROLLBACK = OBSERVED_BUT_GEOMETRY_IDENTITY_NOT_EVALUABLE`
- `ONE_WINDOW_IMPLICIT_REQUALIFICATION = FAIL`
- `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`

No 0.05 s implicit simulation was started.
