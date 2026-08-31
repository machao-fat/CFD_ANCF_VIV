# Stage351 restart bootstrap velocity smoke

Stage351 used the fresh Stage350 candidate, which aligned interface
displacement, velocity, and finite-difference acceleration to Stage341
diagnostics. The real Smoke still failed closed before continuation.

- source: global step `15999`, `79.995 s`
- target: global step `16040`, `80.2 s`, `dt=0.005 s`
- all three slices returned `-8` (`FOAM_SIGFPE`) near `80.025-80.030 s`
- peak Courant values included approximately `674.35` (slice 0000), `3.88`
  (slice 0001), and `13.21` (slice 0002)
- no continuation was started
- exact owned-PID cleanup completed with `owned_residual=0`

This demonstrates that the remaining defect is not limited to restart
displacement or kinematic state alignment. The next repair must inspect the
preCICE/OpenFOAM motion application and mesh-update ordering. This runtime is
terminal and must not be reused; no automatic retry is permitted.
