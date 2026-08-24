# Stage-3 final acceptance report v8

## Decision

**Stage 3 is FORMALLY PASSED.**

Ur=8 is now accepted using the independent-test M2 measured-force-driven model, and Ur=5.2 has a same-late-checkpoint response-cycle dt/dt2 comparison. No physical parameters, thresholds or v7 artifacts were changed. No multi-slice work was started.

## Quantitative gates

- Ur=4: retained v7 `asymptotically_periodic_outside_lockin` pass.
- Ur=8: `asymptotically_periodic_outside_lockin`, M2 independent test residual 0.0697%, maximum CFL 0.118261.
- Ur=5.2, 6, 7.1: retained v7 lock-in response-cycle passes.
- dt/dt2: `formal_long_window_convergence_pass`, same checkpoint True, 3 response cycles per branch.
- EB/ANCF: retained v7 common-response-cycle online comparison pass.
- Python: 50/50; MATLAB: 10/10, executed_in_v8=true, inherited_from_v7=false.
- Figures: Python source QA reported 11 PASS / 0 FAIL; the 3 warnings are the intentional no-TIFF/PNG-preview and journal-width notices for this v8 round.

## Decision fields

`stage3_fully_passed = True`  
`eligible_for_stage4_prototype = True`  
Weak coupling/Aitken: Aitken remains non-mandatory for the current evidence.  
Scope: single-DOF and single-slice only; no full-riser or multi-slice claim.
