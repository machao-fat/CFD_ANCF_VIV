# Stage 363 coherent restart candidate

Stage363 is an offline candidate builder. It binds the completed OpenFOAM
`80` field directory (`global_step=16000`, `time=80.0 s`) to the finalized C++
structure state and the Stage350 bootstrap state. It validates all three slices
have the same field clock and mesh field sizes, then writes only a manifest.

The candidate does not copy or rewrite fields, does not synthesize `phi`,
`meshPhi`, or `Uf`, and launches no MATLAB, OpenFOAM, WSL, or CFD process. A
future Smoke launcher must preserve the source `U` cylinder boundary and
`polyMesh/points` exactly, then audit minimum edge length and Courant number at
the first motion update. Any collapse or spike must fail closed.

Gate: `STAGE4F_D_RESTART_COHERENT_CANDIDATE_V1_GATE: pass`

This is eligibility for one new 40-step Smoke only, not authorization to run
it. No continuation is started automatically.
