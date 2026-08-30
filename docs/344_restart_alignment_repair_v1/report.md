# Stage344 restart alignment repair

Stage341's saved `slice_*/80/pointDisplacement` fields match the retained
mapping diagnostics for `global_step=15999` (`time=79.995 s`), not the final
structure state after `global_step=16000`. Stage343 incorrectly initialized the
fluid restart from `final_q`, causing a boundary displacement jump immediately
after the `80 s` directory was loaded. The resulting Courant spike and
`GAMGSolver::scale` `FOAM_SIGFPE` were therefore a restart state/field
consistency failure, not a storage failure.

This stage only performs binary-field parsing, identity comparison, and a
backward-Taylor state estimate. It starts no MATLAB, OpenFOAM, WSL, or CFD and
does not modify Stage341 or the failed Stage343 runtime.

The next implementation must make synchronization explicit (a bootstrap state
and field contract) and reject direct use of `final_q`. A fresh, short,
explicitly authorized smoke is required before any new long continuation.
