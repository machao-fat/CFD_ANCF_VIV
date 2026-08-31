# Stage 356 restart bootstrap alignment

This is an offline repair after Stage355 showed that the structure state was at
79.995 s while the CFD field was labeled 80.0 s. Stage356 reconstructs the
position, velocity, and acceleration state at 80.0 s from the lag-1 bootstrap
and diagnostics, then applies the same 80.0 s interface positions to all six
cylinder displacement boundaries. It starts no external process and requires a
new explicit one-shot Smoke authorization before execution.
