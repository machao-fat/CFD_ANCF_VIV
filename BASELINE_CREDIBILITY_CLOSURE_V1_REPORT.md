# Baseline credibility closure V1

Scope is limited to MATLAB--C++ ANCF validation and the H/H^T moment audit.
No OpenFOAM, Fluent, preCICE, 370 s continuation, or physical VIV calculation
was started.  Stage341--385 evidence was read only.

| Question | Evidence-backed answer |
|---|---|
| 1. Did MATLAB really run? | Yes. MATLAB R2021b executed the protected ANCF reference and produced `results/validation_matlab_cpp_v1/matlab_reference.json`. |
| 2. Is static equilibrium consistent? | Yes. At all 17 nodes and 16 midpoints, maximum coordinate difference and normalized L2 shape error are 0 at recorded precision. |
| 3. Do the first six modes match? | Yes. Frequencies are 0.1987610, 0.4761819, 0.8702402, 1.3985123, 2.0685949 and 2.8842837 Hz; maximum relative discrepancy is 2.15e-13. |
| 4. Is the 0.20 Hz mode confirmed twice? | Yes. MATLAB gives 0.198761026753895 Hz and C++ 0.198761026753869 Hz. |
| 5. Does free vibration match? | Yes. A common 50 s analytic perturbation, zero velocity/acceleration, zero damping and zero fluid force yields equal 0.19990005 Hz spectra; maximum displacement NRMSE is 3.44e-12 and phase drift is 1.37e-12 rad. |
| 6. `NUMERICAL_CORE_VALIDATED`? | `yes` for this frozen 50 m / 16-element ANCF numerical contract. Core mass, internal force and tangent also match. |
| 7. Root cause of 4.44e-10? | A cancellation-conditioned legacy relative metric. At the worst retained row, net moment is 4.03e-9 N m while individual contributions total 6.74e-2 N m (condition number 1.67e7). |
| 8. Does mapping require a mathematics/code repair? | No. Single-force, pure-couple, non-symmetric, translated-origin and rigid-rotation virtual-work analytical identities pass. |
| 9. Does the metric need versioning? | Yes. Future audits need both absolute moment mismatch and the documented contribution-scale-normalized V2 metric. |
| 10. Do analytical moment tests pass 1e-10? | Yes, for all normal non-pathological cases; near-zero and cancellation cases also pass the conditioned metric. |
| 11. Does historical V3 `MAPPING_INTEGRITY` change? | No. It remains `fail`; Stage385 was not modified or retroactively reclassified. |
| 12. Is a new three-slice 1 s smoke allowed? | `AUTHORIZED`, only as a fresh 1 s force-contract smoke. It must freeze and emit force units, `unit_span_m`, `slice_length_m`, absolute moment error, the versioned normalized moment error, virtual work, force balance, IDs and mesh/solver-quality observables. |

Phase A report: `ANCF_MATLAB_CPP_CROSS_VALIDATION_V1.md`.

Phase B report: `MOMENT_MAPPING_ROOT_CAUSE_V1.md`.

The authorization does not extend to 10 s, 100 s, long VIV, Fluent, or a 370 s
continuation.  The pre-existing formal status claims for Strouhal, stable VIV
response and lock-in remain `not_completed`.
