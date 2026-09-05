# Numerical Quality Evidence Closure V1

## Decision before a fresh run

`FRESH_1S_SMOKE_V2 = AUTHORIZED`.

The authorization is limited to one fresh 200-window / 1.0 s run from `t=0`
at the frozen physical and coupling contract. No OpenFOAM numerical setting is
changed: the only new runtime behaviour is Newton-diagnostic persistence and
the V2 evidence/parser/quality decision. run_008 remains a historical V1
**FAIL** and is not reclassified.

## Residual conclusion

The two V1 values 0.00445800788829 and 0.00462973685818 are non-terminal `p`
solves at `t=0.005` and `t=0.015`, respectively. Their corresponding terminal
`p` residuals are 9.41975628408e-9 and 7.04122362515e-9. The log identifies one
outer corrector and zero non-orthogonal correctors, but does not label pressure
corrector index; it is recorded as `unknown`.

Thus the legacy metric remains a useful intermediate-solve diagnostic, but is
not a valid hard measure of terminal timestep convergence. A post-hoc startup
exemption is neither needed nor introduced.

## Quality Contract V2

V2 separates observability completeness, linear-solver health, terminal
per-field PIMPLE convergence, Courant quality, continuity quality, and
iteration health. It retains the V1 maximum-over-all-solve residual strictly as
a diagnostic. The terminal per-field limits for this unchanged exact solver
configuration are 1e-8 for `Ux`, `Uy`, and `p`, directly matching `UFinal` and
`pFinal` with `relTol=0`. V2 makes no claim that a log line alone proves the
exact named OpenFOAM dictionary entry; its preflight must confirm the frozen
configuration and log parser must retain uncertainty where the stdout omits an
index.

The read-only V2 evaluation of run_008 passes all V2 terminal, Courant,
continuity, iteration and observability gates. This does not modify the V1
classification.

## Newton evidence

Future V2 structure records contain both prediction and correction diagnostics:
iteration count, final residual, derived convergence, finite-state audit,
return code, time/tick/sequence identity, and the SHA-256 linked `q`, `qdot`,
and `qddot` state. The current C++ wire does not send an initial Newton
residual, so no initial residual is invented.

## Prohibited next work

This authorization is not authorization for a 10–20 s physical run. That
decision must wait for the fresh V2 smoke evidence.

## Fresh smoke V2 execution

The authorized fresh case `three_slice_force_contract_smoke_v2_run_001` was
run once from `t=0` to `t=1.0 s`; no run_008 runtime was reused or modified.
All six preCICE participants returned zero, 200 coupled windows committed, and
each slice has 200 force records. The final gate is
`THREE_SLICE_FORCE_CONTRACT_SMOKE_V2 = PASS`.

The force/mapping/displacement checks pass with maximum force error
1.4551915228366852e-11 N, absolute moment error 2.9802322387695312e-8 Nm,
V2 moment error 2.4025997889903465e-16, and normalized virtual-work error
8.512774285412415e-16. All three OpenFOAM V2 evaluations pass: maximum terminal
residuals are `Ux=9.99659849617e-9`, `Uy=8.48413096951e-9`, and
`p=9.983874437e-9`; maximum Courant number is 0.350855773225 and maximum
absolute global continuity error is 1.10665568732e-8.

The structure participant persisted and validated exactly 400 Newton records:
200 predictions and 200 corrections. The C++ worker completed with return code
zero and owned residual zero.

`NEXT_10_TO_20S_PHYSICAL_TEST = CONDITIONAL`: this V2 smoke removes the
force-contract and numerical-quality-evidence blocker, but it does not itself
authorize a physical-duration test. That requires explicit human approval in a
later turn.
