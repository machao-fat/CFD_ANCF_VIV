# Stage350 restart bootstrap velocity repair

Stage349 showed that correcting only the saved displacement did not prevent a
restart transient. Stage350 is an offline repair: it reconstructs a fresh
lag-1 state at `79.995 s` from the finalized Stage341 state and the adjacent
diagnostic records at global steps `15998` and `15999`.

The generated candidate aligns the three slice interface displacement,
velocity, and finite-difference acceleration with the saved diagnostics using
the same canonical ANCF `H` rows. The preparation Gate passed with errors below
`4e-19` in the three audits. No MATLAB, OpenFOAM, WSL, or CFD process was
started. The candidate is not a production result; it still requires a fresh
real Smoke and a passing Smoke Gate before any continuation may start.
