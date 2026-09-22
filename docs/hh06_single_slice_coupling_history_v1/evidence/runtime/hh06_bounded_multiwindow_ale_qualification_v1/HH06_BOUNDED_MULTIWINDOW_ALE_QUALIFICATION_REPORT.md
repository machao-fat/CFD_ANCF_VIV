# HH06 bounded multiwindow ALE qualification

## Final classification

`DO_NOT_PASS`

Primary blocker: `LATE_WINDOW_ALE_FLOW_TURBULENCE_RUNAWAY`

The Force unit-chain pre-gate and the rollback/state-machine checks passed. The bounded run completed 25/25 accepted windows and crossed the previous failure time, but the final windows developed the same qualitative instability chain: rapidly increasing mesh velocity and Courant number, followed by large flow velocity, force and `omega`. The finite process exit at exactly 30.005 s is not accepted as numerical stability.

`HH06_SINGLE_SLICE_FSI_PREPRODUCTION_50WINDOW` is **not authorized** and was not started.

## Phase A — Force unit-chain pre-gate

Status: `PASS`

The nonzero second implicit iteration of the isolated pre-gate gave:

| Quantity | X | Y | Unit |
|---|---:|---:|---|
| OpenFOAM raw integrated force / adapter write sum | 0.06440713207168003 | 0.05908675094604829 | N |
| Conservative mapped and Structure-received force | 0.06440713207168003 | 0.05908675094604829 | N |
| Force per unit span (`/0.028`) | 2.3002547168457155 | 2.1102411052160104 | N/m |
| Strip resultant (`*1.98`) | 4.554504339354517 | 4.178277388327700 | N |
| ANCF worker physical sectional resultant | 4.554504339354517 | 4.178277388327700 | N |

The applied/raw factor was exactly `1.98/0.028 = 70.71428571428571`; maximum closure error was `0`. Scaling occurred exactly once in `ForceSample.from_openfoam_integrated()`. No extra span or strip-length factor was detected.

Full pre-gate evidence:

- `HH06_SINGLE_SLICE_FORCE_UNIT_CHAIN_AUDIT.md`
- `HH06_SINGLE_SLICE_FORCE_UNIT_CHAIN_AUDIT_RESULT.json`

## Phase B — Candidate freeze

The 25-window run loaded the isolated qualified adapter proven through `/proc/<pid>/maps`. No production adapter was overwritten.

| Artifact/configuration | SHA256 |
|---|---|
| Candidate `Adapter.C` | `710F45FBA682442CBEC979D6993A24B2C530B0E592B62C18041D429CA4DD6301` |
| Candidate adapter binary | `8C2C0FDA85DC7ED452EB144B03A92AC9BF739E62EE8369BAF489B3439CFDF458` |
| Qualified SHM1 worker | `69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF` |
| `precice-config.xml` | `350E4AFF17BF39EC2FD48F3FA2A44E5FC9173E040612E84E7D8586F88AFB4C3B` |
| `fvSchemes` | `3C60F43D1CF67043E18F896C783302CA27D30CEB609ABCCB39F1642A8CF6508B` |
| `fvSolution` | `326A2195A56929008CA19BC1B4857600F742460AB798009D9812686997989E87` |
| `dynamicMeshDict` | `56158D50B619174C67A343D2660C87C4C0C5E1370E2FDE44A4A4C6F07C5CCDC5` |
| `momentumTransport` | `41B0F7435366F11A60479BDE4FBC68B08C744EB89C7ED5255FC8CCF7316D229A` |

Frozen runtime conditions were `dt=0.0002 s`, true ANCF displacement, no diagnostic offset, parallel implicit coupling, the qualified SHM1 worker and the existing SST/ALE configuration.

## Phase C — 25-window result

### Coupling and state management

- accepted windows: `25/25`;
- coupling attempts: `50` (two per window);
- genuine rollback/restore operations: `25`;
- Structure physical rollback: exact for all 25;
- Fluid rollback (`points`, `oldPoints`, `U`, `p`, `phi`, `meshPhi`, `k`, `omega`, `nut`, `pointDisplacement`, `cellDisplacement`): exact or initial semantic-zero equivalent for all 25;
- force-chain error across all attempts: `0 N`;
- transport `sequence/request_id/transaction_id`: strictly session-monotonic;
- duplicate IDs, checkpoint errors, worker errors: none;
- ANCF Newton iterations: maximum `4`;
- ANCF residual: maximum `1.051901521442744e-6`.

Thus the earlier rollback/read-path defects are not the direct cause of this failure.

### Mesh and runtime health

| Metric | Observed extremum |
|---|---:|
| OpenFOAM Co mean | 1.050443746 |
| OpenFOAM Co max | **184.6621404** |
| mesh Courant max | **58.75197066197** |
| mesh velocity max | **18.11732438950 m/s** |
| max `|U|` | **392.2742170025 m/s** |
| minimum cell volume | 7.68736492085e-10 m3 |
| maximum non-orthogonality | 44.1041839243 deg |
| maximum skewness | 0.21928340335 |
| `k` min/max | 2.70199253269e-10 / 0.02372623592 |
| `omega` min/max | 1.96472720256 / **925092.968118** |
| `nut` min/max | 2.88080872843e-15 / 2.80561626046e-4 |
| max absolute local continuity error | 7.454802298e-4 |
| max absolute global continuity error | 1.821769753e-4 |
| max received raw-force norm | 2121.13919201 N |
| max applied strip-force norm | 149994.842863 N |
| max structure XY displacement norm | 0.004043076811 m |

All volumes remained positive and the geometric quality metrics remained nearly unchanged. `k`, `omega` and `nut` remained finite, but finiteness alone is insufficient: `omega_max` increased by about 9.9 times from its initial near-wall level while Co, velocity and force grew by orders of magnitude.

### Historical failure region

Values below are the maximum over the two implicit attempts at each physical window:

| Global time (s) | Co max | max `|U|` (m/s) | mesh velocity (m/s) | mesh Co | `omega_max` |
|---:|---:|---:|---:|---:|---:|
| 30.0038 | 1.159879582 | 1.154789409 | 0.631161217 | 2.046766248 | 93792.84755 |
| 30.0040 | 0.411697610 | 5.672046491 | 2.184901954 | 7.085048762 | 93792.84774 |
| 30.0042 | 3.424700471 | 4.736307670 | 2.709128064 | 8.785105266 | 93792.84786 |
| 30.0044 | 2.057914606 | 20.66883973 | 5.132022560 | 16.64102202 | 254850.2393 |
| 30.0046 | 17.61550810 | 16.48624763 | 8.613130629 | 27.92902986 | 366110.1806 |
| 30.0048 | 19.14672405 | 82.83084450 | 10.31033955 | 33.43278707 | 617510.8686 |
| 30.0050 | **184.6621404** | **392.2742170** | **18.11732439** | **58.75197066** | **925092.9681** |

The detailed two-iteration table is preserved in `artifacts/historical_failure_region_per_iteration.csv`; all 25 window records are in `artifacts/window_summary.csv`.

### Fail-closed decision

No field/runtime NaN or Inf, FPE, negative volume, preCICE fatal or ANCF fatal occurred before the deliberately bounded end. Two textual `inf` values in the preCICE log came only from a relative convergence measure with zero normalization (`normalization = 0`, `conv = true`); they are not non-finite CFD or structural fields. Nevertheless, the explicit fail condition `omega nonphysical explosion` was met together with a severe Co/velocity/force runaway. The run ended before the solver had to crash; this cannot be classified as stable multiwindow behavior.

## Process and filesystem boundary

- Phase A real starts: one OpenFOAM, one Structure participant, one worker;
- Phase C real starts: one OpenFOAM, one Structure participant, one worker;
- automatic retries: `0`;
- related residual processes after completion: `0`;
- isolated case numeric directories: only `30`;
- original `slice0000` numeric directories: only `30`;
- 50-window run: not started;
- 0.2 s production run: not started.

## Evidence index

- raw Fluid log: `phase_c_25window/fluid.stdout`
- raw Structure log: `phase_c_25window/participant.stdout`
- Fluid rollback/ALE fingerprints: `phase_c_25window/fluid_rollback_fingerprint.jsonl`
- Structure force/transport/rollback trace: `phase_c_25window/structure_force_trace.jsonl`
- loaded adapter proof: `phase_c_25window/artifacts/fluid_proc_maps_adapter.txt`
- machine-generated audit: `artifacts/run_analysis.json`
- all-window table: `artifacts/window_summary.csv`
- historical-region iteration table: `artifacts/historical_failure_region_per_iteration.csv`

The only valid final classification is `DO_NOT_PASS`. No downstream phase is authorized.
