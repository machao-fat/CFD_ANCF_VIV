# Stage75 candidate 1 attempt10 report

`STAGE75_E5_CANDIDATE_1_GATE: do_not_pass`

The newly isolated runtime completed ten physical CFD steps and all three slices passed process, force, geometry, and checkpoint audits. However, the outer campaign gate still hard-coded `first=520` while the restart contract requires target steps 560--599. The gate therefore rejected the output as an out-of-range identity immediately after block0; no later block started and the runtime was not retried.

The source checkpoint SHA remained unchanged: `341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`. The failure runtime is sealed and residual is zero. The orchestration loop is now repaired to derive block starts from `first_target_step` in the frozen contract. Physical core, protocol, parameters, and thresholds were not modified. A new authorization is required before another fresh attempt.
