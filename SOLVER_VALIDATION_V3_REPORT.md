# Solver Validation V3 Report

## Scope and evidence

This is a read-only credibility audit of the retained 0–370 s three-slice
OpenFOAM 10–preCICE–C++ ANCF campaign. It does not start CFD, Fluent, MATLAB,
preCICE, or a continuation beyond 370 s. Stage341–385 files remain unchanged;
the Stage385 V2 gate and contract SHA-256 values are asserted in
`tests/solver_validation_v3/test_historical_v3_evidence.py`.

The public evidence repository was inspected at commit
`acc54ad18c9a05fbdc552c3ace18bde50aceaa38`. Its README independently records
the same material limitation: no retained `unit_span_m` or slice/tributary
length and direct legacy preCICE vertex-force sums.

## Direct answers

| Question | Answer | Evidence / interpretation |
|---|---|---|
| Q1. Does Stage382 have a complete credible structural force scale? | **not_evaluable** | The historical participant directly summed preCICE vertex forces and supplied them to C++; Stage382 mapping rows contain neither `unit_span_m` nor tributary/slice length. Conservation of that input does not establish its physical scale. |
| Q2. First six C++ ANCF modes, Hz | **0.198761, 0.476182, 0.870240, 1.398512, 2.068595, 2.884284** | C++ static equilibrium, C++ tangent/mass, and mass-normalized transverse-y position/slope generalized modes. The closest mode to 0.20 Hz is mode 1, a difference of 0.001239 Hz. MATLAB comparison is **reference_not_available** because MATLAB was not started. |
| Q3. Can 0.20 Hz persist without damping and fluid force? | **yes, in the controlled C++ test** | With zero mapped fluid force and both damping coefficients zero, a 20 s first-mode perturbation produces 0.199501 Hz. Incremental energy changes by only 1.57e-4 relative. This proves a structurally available free response; it does not by itself reconstruct the historical initial state. |
| Q4. Are individual 220–370 s `Fy_i` statistics stable? | **locally yes, diagnostically** | All three `Fy` RMS drifts are 0.25–0.68%, and FFT-frequency drifts are about 0.10%, under the frozen 5% retrospective local-statistics threshold. This does not cure the separate mapping-integrity failure. |
| Q5. What are local `y_i` frequencies? | **about 0.20007 Hz for all three** | FFT over 220–370 s reports 0.2000667 Hz for each retained local y coordinate. |
| Q6. Are local `f_Fy,i` and `f_y,i` synchronized? | **not supported** | Each local `Fy` is about 0.160053 Hz, while each local y coordinate is about 0.200067 Hz. |
| Q7. What is local `Fy_i`–`y_i` coherence? | **very low** | For 270–370 s at the closest Welch bins: slice 0: 0.00183 / 0.00191 at 0.16 / 0.20 Hz; slice 1: 0.00222 / 0.00203; slice 2: 0.00419 / 0.00427. |
| Q8. What is mean fluid-to-structure power? | **physical power not evaluable** | The numerical raw `Fy*vy` means over 270–370 s are −1.14e-6, −1.07e-7, and −1.91e-6 in legacy-force-scale·m/s. They are not W because the historical force scale is unknown. No claim of sustained positive physical energy input is supported. |
| Q9. Could Stage385 phase-gate failure be beating? | **possible, not proven** | Full-window peak estimates yield `Δf` of 0.00040, 0.00147, and 0.00188 Hz for pairs 0–1, 0–2, and 1–2, implying approximate beat periods of 2478, 679, and 533 s. Such offsets can drift phase, but finite-window peak estimates and waveform differences cannot establish beating as the sole cause. |
| Q10. Does history support stable VIV / lock-in / quantitatively correct response? | **stable VIV: not supported; lock-in: not supported; quantitatively correct response: not evaluable** | Local `Fy` stationarity alone is insufficient. Force scale is unresolved, mapping has a retained relative moment error above contract, and local force/displacement frequencies and coherence do not indicate synchronization. |
| Q11. Continue 370 s to a longer three-slice CFD run now? | **NO** | More runtime cannot define force units, repair a mapping-contract failure, or turn a free structural mode into evidence of fluid lock-in. |

## Force contract

The required future chain is explicit:

```text
OpenFOAM force [N]
  / unit_span_m
= 2-D unit-span force [N/m]
  * tributary_length_m (slice_length_m)
= integrated structural slice force [N]
  -> H^T generalized ANCF load
```

The existing versioned `coupling.multi_slice_mapping` schema requires positive
`unit_span_m` and `slice_length_m`, records all three representations, requires
`force_representation=integrated_slice_force_N`, verifies the conversion, and
fails closed on missing fields. V3 tests cover conversion, missing span,
force/moment conservation and virtual work. The legacy Stage305 participant
does not satisfy this future contract and must not be reused for a formal run.

## ANCF findings and limits

The original MATLAB `vertical_ttr_case.m` explicitly sets Rayleigh alpha and
beta to zero, matching the fixture and C++ model. No damping was added. The
C++ validation boundary currently rejects nonzero damping, so no arbitrary
damping sensitivity parameter was introduced.

The modal/free-vibration evidence is controlled rather than a MATLAB/C++ dual
numerical equivalence proof. Consequently:

```text
C++_ANCF_NUMERICAL_CORE_STATUS = not_completed
MATLAB/C++ modal reference = reference_not_available
```

Nevertheless, the `0.198761 Hz` C++ first transverse mode and `0.199501 Hz`
zero-fluid response make an unforced ANCF modal contribution a concrete,
more plausible explanation for the retained 0.20 Hz coordinate than an
unqualified lock-in claim.

## Local V3 analysis and gate status

`interface_positions_xy` is established by source inspection to be the
absolute ANCF projected interface position. The historical writer misleadingly
aliases it as `displacement_xy` when exporting it to preCICE. V3 therefore
calls the analyzed quantity `local_y_coordinate_m`, not an independently
referenced static-equilibrium displacement.

| V3 layer | Status | Meaning |
|---|---|---|
| DATA_INTEGRITY | pass | 3,000 retained scalar rows from 220–370 s have continuous global steps, 0.05 s cadence, ticks and finite local values. |
| MAPPING_INTEGRITY | fail | Full retained mapping rows have maxima: virtual work 3.77e-13, force balance 1.87e-14, **moment balance 4.44e-10**. The last exceeds the 1e-10 contract; it was not relaxed. |
| LOCAL_STATISTICAL_STABILITY | pass | Local `Fy` and local y RMS/frequency drifts pass the frozen retrospective 5% criteria. |
| LOCAL_FLUID_STRUCTURE_SYNCHRONIZATION | not_completed | Frequency mismatch and very low coherence are reported; no lock-in criterion or physical force scale exists. |
| SLICE_PHASE_COHERENCE | diagnostic | It is intentionally not a primary local-stability veto for independent 2-D slices. |
| PHYSICAL_FORCE_SCALING | not_evaluable | Historical fields are insufficient. |
| FORMAL_LOCK_IN / FORMAL_VIV_VALIDATION | not_completed | No promotion of historical claims. |

## OpenFOAM-quality interpretation

The retained quality parser defines `residual_max` as the maximum **final**
residual among parsed `Solving for` lines; `continuity_global` is the last
parsed global continuity value; and `iterations_max` is the maximum parsed
iteration count. Stage381 and Stage382 have complete quality record streams
for all three slices, so `OBSERVABILITY_COMPLETENESS=pass`.

No frozen pre-run numerical-quality contract (limits plus the exact residual
and continuity semantics) was retained. Therefore
`NUMERICAL_QUALITY=not_evaluable`, rather than incorrectly reporting quality
as pass merely because fields exist.

## Q12 — minimal next validation case

Run **one new 1 s, three-slice force-contract smoke** before any longer CFD:

- duration `1.0 s`; `dt=0.005 s`; 200 coupled steps; no continuation of a
  historical runtime;
- 50 m, 16-element ANCF model; three axial slices at 8.333333, 25.0 and
  41.666667 m; preserve the existing physical parameters and zero damping;
- build an explicit `SliceManifest` with every slice's `s_ref_m`,
  `unit_span_m`, and `tributary_length_m/slice_length_m`; do not use implicit
  values of 1;
- save per step and per slice: raw OpenFOAM force `[N]`, unit-span force
  `[N/m]`, integrated slice force `[N]`, force representation, H/H^T audit,
  reference position, absolute position, displacement, velocity, acceleration,
  global/case-local step, tick, and all identity hashes;
- preserve parsed solver records with declared field definitions and a
  pre-run frozen numerical-quality contract; retain raw log text or per-field
  final/initial residual provenance so numerical limits are interpretable.

It passes only if all fields are present and finite, conversion is exact within
the schema tolerance, force/moment/virtual-work relative errors are below
`1e-10`, terminal records exist for every step and slice, and the predeclared
numerical-quality contract passes. Any missing unit, unqualified force field,
or mapping error fails closed. A 10–20 s physical comparison or further 370 s
continuation is not authorized by this report.

## Reproduction

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python tools/solver_validation_v3/phase1_force_audit.py
python tools/solver_validation_v3/run_ancf_modal_free.py
python tools/solver_validation_v3/reanalyze_historical_v3.py
python tools/solver_validation_v3/audit_openfoam_quality_v3.py
python -m unittest tests/solver_validation_v3/test_force_contract.py tests/solver_validation_v3/test_ancf_modal_free.py tests/solver_validation_v3/test_three_slice_statistics_v3.py tests/solver_validation_v3/test_historical_v3_evidence.py tests/solver_validation_v3/test_openfoam_quality_semantics.py
python tests/multi_slice_mapping/run_tests.py
```

The three evidence-generating commands refuse to overwrite their result files;
their committed outputs are the authoritative V3 record for this audit.
