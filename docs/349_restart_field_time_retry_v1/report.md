# Stage349 restart-field-time retry report

## Outcome

The fresh retry smoke was started only after the offline preparation Gate and
launcher checks passed. It failed closed before continuation.

- run: `run349_restart_field_time_retry_v1_smoke`
- case: `case349_restart_field_time_retry_v1_smoke`
- source mapping: global step `15999`, `79.995 s`
- smoke target: global step `16040`, `80.2 s`, `dt=0.005 s`
- result: `STAGE4F_D_RESTART_BOOTSTRAP_REAL_SMOKE_V1_GATE: do_not_pass`
- continuation: not started

## Failure evidence

All three OpenFOAM quality records terminate with return code `-8`
(`FOAM_SIGFPE`) near `80.025-80.030 s`. The recorded peak Courant numbers
were approximately `67.76`, `14.70`, and `31.16` for slices 0000, 0001, and
0002. The structure participant did not finalize all 41 steps. The launcher
was then stopped by exact owned-PID cleanup; no process was killed by name.

The retry runtime and its evidence are terminal and must not be reused. The
Stage341 source runtime remains read-only. No MATLAB was started; the failed
smoke started three OpenFOAM processes, one WSL shell, one C++ worker, and one
preCICE structure participant, all cleaned with `owned_residual=0`.

No completion wall-clock estimate is applicable because the `200 s`
continuation was never eligible to start. The next action requires a new
offline repair/preflight and a new explicit authorization.
