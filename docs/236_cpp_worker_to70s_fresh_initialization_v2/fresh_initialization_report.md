# Stage 236 fresh initialization package

- Three new cases were materialized from the matching mesh and uniform U/p template.
- phi, Uf, and meshPhi are explicit zero-time seed files for solver-side derivation.
- A straight ANCF reference vector is recorded for audit only; the MATLAB static-equilibrium script must produce the authoritative state.
- No MATLAB, OpenFOAM, WSL, or CFD process was started.
- Gate: STAGE4F_D_FRESH_INITIALIZATION_PACKAGE_V1_GATE: do_not_pass until ancf_t0_state.mat is produced and audited.
