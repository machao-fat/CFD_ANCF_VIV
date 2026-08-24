# Ur=8 final classification v8

Classification: **asymptotically_periodic_outside_lockin**.

- Final independent test residual: 0.0697% (<15%).
- Full-tail residual after the selected-model refit: 0.0513% (<15%).
- Response frequency: 0.159454346 Hz; f/fn=1.275635.
- Force/Cl RMS validation-to-test change: 2.363%.
- M2 measured-force-equivalent forced amplitude change: 0.853%.
- Homogeneous decay rate: 0.007853982 s^-1; theory 0.007853982 s^-1.
- Phase drift relative to Fy for M2: -0.090543 rad across the full tail.
- Maximum CFL: 0.118261; maximum |y|: 0.052018 m.

The v7 22.47% failure was caused by the old fixed-frequency/fixed-phase comparison and, in the first v8 attempt, omission of the preserved 200.0025--221.25 s interrupted audit segment. After restoring the complete time record, M2 separates the recorded force modulation from the homogeneous component. No physical parameter or acceptance threshold was changed, and no Ur-specific classifier branch was added. No additional Ur=8 CFD was run in v8.
