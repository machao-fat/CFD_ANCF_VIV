# PRECONDITIONED_FORCE_ESCALATION_AND_MESH_AUXILIARY_ROOT_CAUSE_AUDIT_V1_REPORT

## Scope and source

- Immutable source: `runtime/preconditioned_coupled_0p1s_smoke_v1_run_003`.
- No new fully coupled run was started. The only executions were a C++ ANCF recorded-load replay, a three-case prescribed recorded-motion CFD replay, and a three-case mesh-only replay, each ending at the existing 0.100 s window.

## Raw streamwise force history [N per 1 m CFD span]

| step | tau [s] | slice 0 | slice 1 | slice 2 |
|---:|---:|---:|---:|---:|
| 1 | 0.005 | 1248.2 | 1248.2 | 1248.2 |
| 2 | 0.010 | 1314.34 | 1314.34 | 1314.34 |
| 3 | 0.015 | -1008.38 | -957.799 | -1007.91 |
| 4 | 0.020 | 522.952 | 337.429 | 526.289 |
| 5 | 0.025 | 4727.58 | 4427.92 | 4733.18 |
| 6 | 0.030 | -1197.46 | -379.911 | -1198.99 |
| 7 | 0.035 | -6535.1 | -6108.6 | -6537.62 |
| 8 | 0.040 | 9839.56 | 7024.27 | 9864.05 |
| 9 | 0.045 | 11043.9 | 11815.6 | 11059.7 |
| 10 | 0.050 | -25494.3 | -17997.2 | -25549.4 |
| 11 | 0.055 | -4784.58 | -11997.9 | -4769.1 |
| 12 | 0.060 | 61949.5 | 46598.4 | 62120.3 |
| 13 | 0.065 | -26000.2 | 3280.89 | -26113.2 |
| 14 | 0.070 | -115061 | -94244.2 | -115394 |
| 15 | 0.075 | 133612 | 46333.9 | 134161 |
| 16 | 0.080 | 170256 | 173987 | 170804 |
| 17 | 0.085 | -395755 | -184366 | -397455 |
| 18 | 0.090 | -114977 | -259553 | -115181 |
| 19 | 0.095 | 975106 | 529377 | 979816 |
| 20 | 0.100 | -360340 | 261231 | -362773 |

- The first material force departure is at step 3 (`tau=0.015 s`): pressure reverses the streamwise force from about +1.31 kN to about -1.01 kN. At step 5 it reaches +4.73 kN; this is 3.50 times the precursor terminal 1.350 kN before the high-velocity excursion is established.
- Maxima: slice 0: |Fx|=975106.246 N at tau=0.095 s (722x precursor; pressure=967692.111 N, viscous=7414.13471 N); slice 1: |Fx|=529376.66 N at tau=0.095 s (392x precursor; pressure=526126.89 N, viscous=3249.77051 N); slice 2: |Fx|=979815.894 N at tau=0.095 s (726x precursor; pressure=972369.164 N, viscous=7446.7296 N).
- The escalation is pressure-dominated. Viscous Fx remains much smaller until the extreme final transients.

## One-way replays

- ANCF recorded-force replay: `PASS`; 20/20 predictor and corrected local states match the coupled record exactly (maximum error `0`).
- CFD recorded-motion replay uses the verified one-window time layer, not a direct same-stamp table. Its maximum normalized raw-Fx errors are slice 0: 0.3624%, slice 1: 0.1181%, slice 2: 0.3651%. Thus it reproduces the escalating force history to sub-0.4% of each slice's force range.
- Mesh-only exact-motion replay: `PASS` for all slices: 20/20 mesh updates reported `Mesh OK`, with no negative-volume mention. This rules out a geometry collapse within this 0.1 s recorded history.

## Coupling and energy

- The discrete timeline has a real one-window geometry-to-force layer: the raw `F_n` stamped at `t_OF,n` matches geometry sent in the preceding explicit window. The structure correction uses that fresh `F_n`; no stale/default force or extra two-window alias was found.
- Midpoint streamwise work (using the prediction/correction velocity midpoint, hence an algorithmic diagnostic) is slice 0: -144555.444 J; slice 1: 52058.5291 J; slice 2: -146068.166 J. It is not sustained positive across slices; the total is -238565.082 J.
- Added-mass-like causality is not established: same-step force/velocity and force/acceleration correlations are sign-changing, while one-window correlations are expected from the explicit time sequence.

## Mesh auxiliary solve semantics

- At `t_OF=0.115 s`, source V3 records 310/233 `cellDisplacementx/y` iterations but final residuals `9.074e-09` / `9.528e-09`, satisfying the actual `fvSolution` `tolerance 1e-8`, `relTol 0` configuration. `fvSolution` does not specify `maxIter 200`.
- The exact-motion mesh-only replay reproduces nontrivial high PCG work (at the corresponding early moving step approximately 236/205 iterations) while all 20 meshes remain healthy. Therefore high iteration count is a conditioning/efficiency warning, not direct proof that the displacement solve is invalid. The historical V3 failure remains a failure; it is not reclassified.
- A future-only Quality V4 proposal is saved at `results/preconditioned_force_escalation_and_mesh_auxiliary_root_cause_audit_v1_run_001/openfoam_quality_contract_v4_proposal.json`: final residual/finite/missing-field remain hard gates; auxiliary iteration count becomes a warning unless a separately frozen solver max-iteration contract exists.

## Decision

- Primary root cause: `FLUID_FORCE_ESCALATION_DRIVES_STRUCTURE within the recorded explicit closed loop; both one-way paths reproduce their respective source histories.`
- Secondary issue: `MESH_AUXILIARY_CONDITIONING: high cellDisplacement PCG iterations recur in mesh-only replay, but all recorded final residuals meet the fvSolution 1e-8 tolerance and mesh-only geometry remained Mesh OK for 20/20 steps.`
- `NEXT_COUPLED_RUN = NOT_AUTHORIZED`
- Minimal next task: a dedicated parallel-explicit FSI stability / time-layer study, beginning from this verified precursor state and changing exactly one stability control at a time only after a new frozen contract. It must not be a longer production run.
