# Stage342 convergence observability repair

This offline stage parses the retained Stage341 OpenFOAM stdout streams. It
does not start MATLAB, OpenFOAM, WSL, CFD, or modify the Stage341 runtime.

The parser accounts for OpenFOAM's output order: a Courant line printed before
the next `Time` marker belongs to that next time step. The result is a compact
one-row-per-step `openfoam_quality.jsonl` containing Courant maximum, solver
residual maximum, continuity global error, and iteration maximum for all three
slices. The audit rejects missing, non-finite, or time-misaligned records.

The quality evidence can remove the previous `missing quality observables`
reason, but it cannot change the Stage341 formal convergence result. Frequency
and force amplitude remain non-stationary in the 0--80 s window.

A run beyond 80 s requires a new explicit authorization and a fresh runtime;
the old Stage341 runtime remains read-only evidence.
