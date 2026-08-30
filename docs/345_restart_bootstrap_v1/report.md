# Stage345 restart bootstrap repair report

## Result

`STAGE4F_D_RESTART_BOOTSTRAP_SMOKE_V1_GATE: pass`

This is an offline protocol result. It is not authorization to resume
Stage343 or to run a new CFD segment.

## Root cause addressed

The Stage341 saved OpenFOAM fields correspond to mapping step `15999` at
`79.995 s`, while the structure checkpoint is finalized at global step
`16000` and `80.0 s`. Restarting the fluid with `final_q` therefore creates a
boundary displacement jump. The new contract represents the mismatch
explicitly with a two-step bootstrap state at `79.99 s`, and requires two
bootstrap acknowledgements before normal continuation.

## Changes

- Added `src/coupling/restart_bootstrap_v1/protocol.py` and package exports.
- Added an offline restart-aware smoke coordinator and machine-readable event
  evidence under `tools/stage345_restart_bootstrap_v1` and
  `results/345_restart_bootstrap_v1`.
- Added validation for run/case identity, canonical time/tick, request and
  transaction IDs, sequence, state/field lag, q hash, producer/consumer,
  stale/duplicate/out-of-order acknowledgements, and direct `final_q` use.
- Added ten protocol/preparation tests and retained the Stage341 source as
  read-only.

No ANCF/EB core, physical parameter, global `dt`, slice count, numerical
threshold, scheduler, checkpoint semantics, or formal 0.2.1 protocol was
modified.

## Verification

- Stage345 compileall: pass.
- Stage345 preparation tests: 1 pass.
- Stage345 bootstrap protocol tests: 9 pass.
- Stage344 restart-alignment regression: 4 pass.
- Restart bridge/time contract regressions with `PYTHONPATH=src`: 16 pass.
- Bootstrap smoke: pass; accepted windows `[0, 1]`.
- Real process starts: MATLAB `0`, OpenFOAM `0`, WSL `0`, CFD `0`.
- Owned residual: `0`.

The Stage343 failed runtime was not resumed or retried. Its evidence remains
protected, and the Stage341 source runtime was read only.

## Next step

The offline repair is eligible for a **new explicit authorization** for a
fresh, short restart-aware real smoke using a new `stage_id`, `run_id`,
`case_id`, and runtime. Only after that smoke proves the first two bootstrap
windows and clean process ownership may a separate authorization be requested
for the `80 s -> 200 s` continuation. No such real smoke was started here.
