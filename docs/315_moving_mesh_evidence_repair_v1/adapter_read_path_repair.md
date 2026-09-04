# Adapter read-path repair

The OpenFOAM adapter's explicit execution path wrote force data and called
`advance()`, but did not call `readCouplingData()`. The OpenFOAM 10 function
object wrapper does not expose the legacy `adjustTimeStep` callback that used
to perform this read. Consequently, received displacement was not copied into
`cellDisplacement`/`pointDisplacement` before the next CFD step.

The isolated source repair adds a guarded `readCouplingData(0.0)` immediately
after `advance()`. The guard skips the terminal step after preCICE has ended,
avoiding access to released coupling objects. This is an adapter-only change;
ANCF/EB code, physical parameters, timestep, slice count, thresholds, formal
protocol, and protected runtimes are unchanged.

The adapter library must be rebuilt offline for the change to affect a future
run. No real CFD run is authorized by this repair itself. A new fresh short
smoke with a new runtime/run/case identity is required after the build.
