# THREE_SLICE_FORCE_CONTRACT_SMOKE_V1 report

## Decision

`THREE_SLICE_FORCE_CONTRACT_SMOKE = FAIL`.

This is the fresh `three_slice_force_contract_smoke_v1_run_008` execution. It used the frozen 50 m, 16-element, zero-damping ANCF contract; `dt = 0.005 s`; and exactly 200 coupled windows from `0.005 s` through `1.000 s`. It is not a VIV-production result.

The original raw runtime and logs are retained at `runtime/stage_force_contract_smoke_v1_run_008`. The authoritative post-run, read-only audit is `results/three_slice_force_contract_smoke_v1_run_008_reaudit_v2/three_slice_force_contract_smoke_v1_gate.json`. The earlier run-local gate is also retained and is not overwritten.

## Contract answers

1. **OpenFOAM unit span:** `1.0 m`, from the actual source mesh point-coordinate extent `z_min = 0 m`, `z_max = 1 m`; it was not inferred from a generic two-dimensional convention.
2. **Tributary lengths:** bounded midpoint/Voronoi partition over `[0, 50] m` gives slice 0 `[0, 16.666666666666668] m`, slice 1 `[16.666666666666668, 33.33333333333333] m`, and slice 2 `[33.33333333333333, 50] m`. Their lengths are respectively `16.666666666666668 m`, `16.66666666666666 m`, and `16.66666666666667 m`.
3. **Coverage:** the tributary lengths sum to `50.0 m`, equal to the represented structural interval.
4. **Force chain:** all 600 slice-step records satisfy `F_OF [N] / 1.0 m = f_2D [N/m]` and `f_2D * L_tributary = F_slice [N]`. Maximum absolute arithmetic identity error is `0.0 N`.
5. **C++ input representation:** the worker receives `integrated_slice_force_N`, i.e. `F_slice [N]`, never raw OpenFOAM force or a line force.
6. **Implicit force scaling:** none. `unit_span_m` and calculated `slice_length_m` are present in every load record.
7. **Position semantics:** separated. Every motion record stores reference position, absolute position, displacement, velocity, and acceleration; maximum `r_abs - r_ref - u` error is `0.0 m`.

## Mapping and coupling answers

8. **Maximum absolute moment mismatch:** `2.980232238769531e-08 Nm`, below the frozen `1e-07 Nm` limit.
9. **Maximum contribution-scale-normalized V2 moment error:** `2.4025997889903465e-16`, below `1e-12`.
10. **Maximum normalized virtual-work error:** `8.512774285412415e-16`, below `1e-12`.
11. **Maximum force balance error:** `1.4551915228366852e-11 N`, below `1e-08 N`.
12. **preCICE exchange:** all three structure-fluid pairs completed all 200 windows. The C++ wire sequence reached prediction/correction sequence 1 through 400; all worker return codes were zero.
13. **ANCF worker:** process completion, finite state audit, and owned-process cleanup passed. However, this run's writer did not persist per-correction Newton iteration count and residual, although those values are present on the worker response wire. Consequently `ANCF_SOLVER_EXECUTION = not_evaluable` under the requested evidence standard, rather than claiming a fully audited Newton pass.
14. **OpenFOAM participants:** all three exited normally (`structure_return=0`, `fluid_0000_return=0`, `fluid_0001_return=0`, `fluid_0002_return=0`).

## OpenFOAM observability and quality

15. **OBSERVABILITY_COMPLETENESS:** PASS for all three OpenFOAM logs after the read-only re-audit. Each has 200 complete, finite, monotonic records from `0.005 s` to `1.000 s` at `0.005 s` increments.
16. **NUMERICAL_QUALITY:** FAIL for all three slices under the frozen contract:

- Courant limit `0.5`; observed maximum `0.350855773225` (pass).
- Final-residual definition `max_final_residual_across_all_parsed_Solving_for_lines_per_time`; frozen threshold `0.001`; observed maximum `0.00462973685818` (fail).
- Residual violations occur at `0.005 s` (`0.00445800788829`) and `0.015 s` (`0.00462973685818`) for every slice.
- Global continuity threshold `1e-06`; observed maximum absolute value `8.6933029158e-14` (pass).
- Iteration failure threshold `999`; observed maximum `23` (pass).

The independent OpenFOAM `forces` function-object reconciliation against the summed preCICE force passes at every retained time, with maximum absolute difference `4.630419425666332e-08 N`, below the frozen `1e-06 N` tolerance.

## Discovered issues

1. The frozen residual threshold is violated at two startup windows in every slice. It cannot be relaxed after this execution.
2. C++ Newton residual and iteration fields were consumed successfully but not persisted in the smoke evidence writer; this prevents a complete Newton-convergence audit.
3. The original post-run audit had two parser defects: a literal `\\d` force-data regular expression and an OpenFOAM10 Courant-before-`Time` association error. They were fixed, tested, and the raw run was re-audited without rerunning CFD.

## Required next action

Do not authorize a 10--20 s physical test. The smallest valid remediation package is: retain C++ Newton residual/iteration evidence per correction and establish a numerically justified residual-quality configuration in a new, pre-run-frozen contract; then run a fresh 1 s smoke from `t=0`. No historical Stage341--385 evidence is modified.

Formal physical conclusions remain:

```ini
PHYSICAL_VIV_STATUS=not_evaluated
LOCK_IN_STATUS=not_evaluated
STROUHAL_STATUS=not_evaluated
NEXT_STAGE_10_TO_20S_PHYSICAL_TEST=NOT_AUTHORIZED
```
