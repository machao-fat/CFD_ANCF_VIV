# Stage 366 lag-1 coherent restart candidate

Stage366 is an offline candidate builder following Stage364's failure. It
binds the OpenFOAM `80` field clock to the Stage350 lag-1 structure state at
`79.995 s`, which the direct boundary comparison proves is the geometry stored
in all three `80` directories. It also verifies that the source cylinder `U`
boundary retains the evaluated nonuniform moving-wall values.

Only a manifest is written. No source field is copied or modified, and no
MATLAB, OpenFOAM, WSL, or CFD process is launched. A new 40-step Smoke requires
an explicit authorization and a fresh runtime; the first motion update must
still pass mesh-quality and Courant audits.

Gate: `STAGE4F_D_RESTART_LAG1_COHERENT_CANDIDATE_V1_GATE: pass`
