# Stage 368 restart-continuation diagnostic

This stage is offline-only. It reads the preserved Stage 341 source and the
preserved Stage 367 failed smoke. It does not start MATLAB, OpenFOAM, WSL, or
the CFD worker, and it does not modify either runtime.

The report separates field/time binding, mesh-motion quality, preCICE timing,
and pressure-solver failure. A `do_not_pass` result is intentional until a
fresh candidate passes the preflight checks and a new, bounded smoke is run.
