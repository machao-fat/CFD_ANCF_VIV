# Stage347 restart bootstrap smoke

The fresh `lag=1` bootstrap smoke was started with new identities and runtime.
It failed closed before continuation: all three OpenFOAM slices reached the
restart window, then encountered `FOAM_SIGFPE` in the GAMG/PCG path around
`80.030-80.035 s`. The largest observed Courant number was approximately
`67.76`. The structure participant did not finalize, and no continuation was
started. Owned processes were explicitly cleaned; owned residual is `0`.

The failure is preserved under `runtime/stage347_restart_bootstrap_lag1_smoke_v1`
and its Gate is `do_not_pass`. No Stage343 runtime was reused.
