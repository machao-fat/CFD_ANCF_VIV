# Stage 4E-B2-A-v2.3.1 scenario-S closeout

## Scope

This report records the single authorized real OpenFOAM 10 `kOmegaSSTLM`
scenario-S medium-mesh run. The run used the pre-declared upper transition
sensitivity input and the same medium mesh, U/p source, perturbation format,
fixed time step, and solver settings as scenario N. No fine run, third
transition level, third model, low/middle case, nine-slice case, or ANCF case
was started.

## Authorization correction

The v2.3 authorization record incorrectly treated the N low-amplitude result
as a blocker. The corrected rule is: N status `rejected_low_amplitude` or
`transition_not_activated`, together with a passing kOmegaSSTLM source audit,
authorizes the pre-declared S case exactly once. It does not authorize tuning
or fine.

The S inputs were frozen before the run: U=0.43414375179615955 m/s,
D=0.02841 m, nu=1e-6 m2/s, rho=1000 kg/m3, Re=12334.023988528894,
Tu=4.472135954999579 percent, k=0.000565442391670936 m2/s2,
omega=305.627421187018 1/s, ReThetat=132.86363717120778, and gammaInt=1.

## Real solver evidence

The fresh S case completed the 10-step preflight and production continuation
blocks to 2, 4, 6, and 9 s. Every accepted block returned zero and contained
`End`. Production used fixed dt=0.0001 s and force/forceCoeffs sampling every
5 steps, giving 14,001 samples over 2--9 s. The maximum production CFL was
0.1366819923969757. The maximum cylinder-patch yPlus p95 over the recorded
endpoints was 0.3953372410487625.

Raw total forces and forceCoeffs matched at every production sample; the
reported relative cross-check errors were zero at the stored precision. The
normalization uses the actual two-dimensional mesh thickness b_mesh=D and
does not apply slice length.

## Statistical conclusion

The three production windows remained below the frozen Cl fluctuation RMS
evaluability threshold of 0.001. Diagnostic FFT and zero-crossing values were
therefore not promoted to a physical frequency or Strouhal number. Effective
cycles are zero under the frozen gate. The S case is classified as
`rejected_low_amplitude`; it is not a frequency-resolved URANS result.

The combined N/S engineering status is
`both_authorized_kOmegaSSTLM_scenarios_rejected_low_amplitude`. The auxiliary
high-Re 2D URANS line remains closed pending Sol review. This evidence does
not establish high-Re physical validity, nine-slice CFD, VIV, lock-in, or
experiment agreement.

## Reproducibility and hygiene

The run ID is
`20260816T050348614Z_stage4e_route1_plus_2_v2_3_1_scenarioS`.
All controllable runtime files were written below the D-drive task runtime
root. The old v2.3 evidence was read-only and its audit has no mismatches.
All task-owned processes were closed and no retained process was handed off.

Primary evidence is in
`results/10_stage4e_route1_plus_2_v2_3_1/`.
