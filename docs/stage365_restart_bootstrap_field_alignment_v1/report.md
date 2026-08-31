# Stage 365 bootstrap/field alignment audit

Stage364 showed that using Stage341's finalized structural state at 80 s did
not match the geometry stored in the OpenFOAM `80` directory. This offline
audit compares both candidates directly. The `80` field's cylinder
`pointDisplacement` matches the Stage350 bootstrap projection from `79.995 s`
to machine precision (`<1e-12 m`) in all three slices. The Stage341 finalized
state has a distinct displacement and therefore cannot be paired with that
field without an additional completed output step.

The next candidate should use the lag-1 bootstrap state while keeping the
OpenFOAM field clock at `80.0 s`. This is an explicit restart convention, not a
claim that the lagged state is a new physical solution. A new 40-step Smoke is
required to test it; this stage launches no real process.

Gate: `STAGE4F_D_RESTART_BOOTSTRAP_FIELD_ALIGNMENT_V1_GATE: pass`
