# PRECURSOR_TRANSFER_AND_STRUCTURAL_MEAN_LOAD_CLOSURE_V1

## Scope and evidence protection

- No coupled CFD, preCICE, Fluent, or MATLAB was started.
- Historical V1 zero-motion restart remains **FAIL**: its first advanced-step jump was 101.994411331 N, exceeding its frozen 100 N absolute limit. This report does not alter V1.
- All CFD quantities below are read from the immutable run_002 raw artifacts.

## Dynamic restart decomposition

At 0.105 s, dynamic minus precursor-terminal total Fx is -101.994411331 N (absolute jump 101.994411331 N). Its direct components are pressure -88.8562885004 N and viscous -13.1381228301 N: the 101.994 N V1 failure is therefore 87.1% pressure-path and 12.9% viscous-path. It is not a revived cold-start impulse. Relative to the fixed restart, the first-step difference is also pressure dominated.

| t (s) | fixed Fx (N) | dynamic Fx (N) | abs difference (N) | dynamic-fixed pressure (N) | dynamic-fixed viscous (N) |
|---:|---:|---:|---:|---:|---:|
| 0.105 | 1320.477922 | 1248.203924 | 72.273998 | -75.218124 | 2.944126 |
| 0.110 | 1292.918248 | 1314.335031 | 21.416784 | 19.115243 | 2.301540 |
| 0.115 | 1267.362373 | 1274.651665 | 7.289293 | 5.491942 | 1.797351 |
| 0.120 | 1243.948248 | 1249.828647 | 5.880399 | 4.466369 | 1.414031 |

The branch difference decays monotonically across all four advanced steps. Dynamic restart force remains 0.07554 of the precursor terminal force and 2.535 times the terminal-tail successive-variation diagnostic. The latter is diagnostic only because the tail is a deterministic monotone decay, not a stationary noise estimate.

## Quality Contract V3

V3 classifies (rather than ignores) `cellDisplacementx/y` as displacement-Laplacian mesh-motion auxiliaries and `pcorr` as a `correctPhi`/`correctMeshPhi` flux auxiliary. Exact-zero/zero-iteration mesh equations are explicit trivial convergence; nonzero mesh equations must satisfy their actual `cellDisplacementFinal` tolerance. `pcorr` must satisfy the real `pcorrFinal` tolerance (1e-2). Ux, Uy and p retain terminal PIMPLE gates. Unknown solver fields fail closed.

- `OPENFOAM_QUALITY_V3 = PASS`
- `PRECURSOR_TRANSFER_V2 = PASS`

## ANCF mean-drag static initialization

The static input is exactly 1350.198335726 N per 1 m CFD span multiplied once by 50/3 m: 22503.3055954 N at each of the three structural slice locations. The force representation remains `integrated_slice_force_N`, mapped through the unchanged H-transpose path.

- Max generalized static residual: 0.00545187899843; frozen mixed-conjugate-unit tolerance 0.0217910400298.
- Max streamwise static deflection: 0.289824019056 m.
- C++/formal H-transpose max absolute difference: 0; force/moment/virtual-work mapping status: `PASS`.

| slice | s (m) | ux relative to no-flow equilibrium (m) | uy relative to no-flow equilibrium (m) |
|---:|---:|---:|---:|
| 0 | 8.33333333333 | 0.180071960812 | 0 |
| 1 | 25 | 0.286929635563 | 0 |
| 2 | 41.6666666667 | 0.135465311232 | 0 |

The ANCF-only normal-drag step applies the same three integrated loads from the no-flow static state for 1 s at dt=0.005 s. It gives max |ux|=0.19819555794 m and max |vx|=0.385712362599 m/s; classification is `BOUNDED`. This is compared only as a startup scale against historical cold-start values near 0.73 m and 184 m/s, whose fluid hydrodynamics remain invalid/not-evaluable.

## Decision

- `STRUCTURAL_MEAN_LOAD_STATIC_EQUILIBRIUM = PASS`
- For a future **mean-flow/VIV** study, `MEAN_DRAG_EQUILIBRIUM` is physically preferable because it removes the finite mean drag step. It cannot yet be paired with the current exported CFD field: that field has a zero-displacement/reference mesh, while the new static equilibrium is deflected by up to 0.289824 m. A static-deflected CFD mesh/state transfer must be independently contracted first.
- For a narrowly scoped immediate 0.1 s coupling probe, `NO_FLOW_EQUILIBRIUM + zero-displacement precursor state` is geometrically consistent; its ANCF-only response reaches only 0.004209 m and 0.07482 m/s by 0.1 s under the normal mean force. That is an option for a separate authorization, not an action here.
- `NEXT_COUPLED_0P1S = CONDITIONAL`. No coupled run was started.

`STRUCTURAL_MEAN_LOAD_INITIALIZATION` was closed only as an ANCF static/step-load study; a future coupled contract must explicitly select and hash the chosen structural state.
