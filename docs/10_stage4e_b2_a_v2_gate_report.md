# Stage 4E-B2-A-v2 Gate candidate

## Status

`candidate_not_passed` for run `20260814T154500000Z_stage4e_b2_a_v2_registryfix`.

The offline contracts, fresh-case checks, six real prechecks, force normalization, raw-force crosscheck, independent yPlus parsing, and process cleanup passed. The formal high-laminar-medium case did not pass the CFL hard stop: the maximum history value was `1.706483721948689` against the hard limit `0.8`. The workflow therefore stopped before formal SST screening and before mesh convergence, dt/dt2 convergence, domain sensitivity, low/middle/high confirmation, and epsilon sensitivity.

The result is a truthful partial pilot, not a Gate pass. No frequency, Strouhal, model-selection, VIV, nine-slice or ANCF claim is made. The recommended next action is to redesign/calibrate the formal timestep against the complete CFL history and start another unique run_id; thresholds must not be relaxed.
