# Stage 364 coherent restart Smoke

This is the user-authorized fresh 40-step Smoke from the completed Stage341
`80.0 s` field. Unlike the rejected Stage361 attempt, the structure initial
state is Stage341's finalized `final_q/final_qdot/final_qddot` at global step
16000, rather than the lag-1 79.995 s bootstrap state. The three OpenFOAM 10
fields are copied from the `80` directory without reserialization.

The launcher is one-shot and fail-closed. It writes a new run/case/runtime,
does not start continuation automatically, and records OpenFOAM quality,
identity, checkpoint, mapping, and process evidence. A nonzero return,
missing step, mesh collapse, or quality failure makes the Gate fail.

Gate: `STAGE4F_D_RESTART_COHERENT_SMOKE_V1_GATE`
