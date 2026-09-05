# Three-slice Force Contract Smoke V2

## Result

`THREE_SLICE_FORCE_CONTRACT_SMOKE_V2 = PASS` for the one fresh 1.0 s run
`three_slice_force_contract_smoke_v2_run_001`.

## Contract evidence

- 200/200 coupled windows committed; 600/600 slice force records are present.
- Unit span remains 1.0 m from the actual OpenFOAM mesh z extent.
- Midpoint/Voronoi tributary lengths are 16.666666666666668 m,
  16.66666666666666 m, and 16.66666666666667 m; their sum is 50 m.
- OpenFOAM force N -> N/m -> integrated slice N identities pass.
- Maximum mapping force error: 1.4551915228366852e-11 N.
- Maximum absolute moment error: 2.9802322387695312e-8 Nm.
- Maximum V2 normalized moment error: 2.4025997889903465e-16.
- Maximum normalized virtual-work error: 8.512774285412415e-16.

## Numerical quality V2

Each fluid slice passed observability, linear-solver health, terminal per-field
PIMPLE convergence, Courant, continuity, and iteration gates. The legacy
maximum intermediate residual is retained as a diagnostic
(0.00462973685818); it is not the V2 hard gate. The maximum terminal field
residuals are `Ux=9.99659849617e-9`, `Uy=8.48413096951e-9`, and
`p=9.983874437e-9`, all within the frozen 1e-8 per-field terminal limit.

## ANCF Newton evidence

Exactly 400 persisted `ancf-newton-evidence-v1` records are valid: one
prediction and one correction for every coupled window. They include only wire
fields actually returned by the C++ worker: iterations, final residual, return
code and finite audit. The convergence flag is explicitly marked as derived
from zero return plus the kernel's throw-on-nonconvergence behaviour. No Newton
initial residual was invented.

## Scope boundary

This is a contract/numerical-quality smoke, not a VIV response study. It makes
no Strouhal, lock-in, amplitude-convergence, or stable-VIV claim.

`NEXT_10_TO_20S_PHYSICAL_TEST = CONDITIONAL`; no longer run was started.
