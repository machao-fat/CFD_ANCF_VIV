# Stage-3 final acceptance report v7

## Decision

**Stage 3 is CONDITIONALLY PASSED / NOT CLOSED.** The v7 science repair closes the Ur=4 interpretation. The Ur=8 extension to 240 s was completed without safety failure but still fails the shared prediction-residual gate, so it remains explicitly unresolved. The project also cannot be declared formally complete while the long-window dt/dt/2 gate is open.

## Quantitative evidence

- Ur=4: class `asymptotically_periodic_outside_lockin`, response 0.175476 Hz, f/fn 0.7019, tail free/forced ratio 0.052%, fit residual 7.79%, prediction residual 7.37%.
- Ur=8: class `outside_lockin_model_failed`, response 0.159454 Hz, f/fn 1.2756, tail free/forced ratio 12.003%, fit residual 12.56%, prediction residual 22.47%.
- Existing dt/dt/2 screen passes its short-window criteria, but it covers only 0.9615 cycles; formal long-window convergence is not claimed.
- Python v7 regression: 40/40; MATLAB: 10/10 (current v7 execution).

## Physics and scope

The Ur=4 and Ur=8 results are classified as asymptotically periodic outside lock-in only when the shared force-frequency, RMS, fit, prediction, decay, energy, CFL and finite-value gates pass. They are not used to claim a strict raw single-frequency limit cycle. Ur=5.2/6/7.1 retain the v6 measured-response-cycle lock-in evidence. No physical parameters, damping, safety limits or acceptance thresholds were changed.

The weak-coupling energy defect remains around 1e-6 J while locked-case cycle fluid work is O(1e2) J. There is no evidence in the current evidence set that Aitken is required as a mandatory single-slice gate; the unresolved item is dt/dt/2 long-window evidence. No multi-slice or full-riser validation was started.

## Blocking items

- Ur8 asymptotic outside-lock-in classification failed: prediction residual gate remains open
- dt/dt2 evidence is an existing 0-10 s, 0.9615-cycle scheme-B screening only; long-window scheme-A gate remains open
