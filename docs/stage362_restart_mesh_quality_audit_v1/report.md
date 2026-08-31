# Stage 362 restart mesh-quality audit

This is a read-only audit of the Stage360 restart candidate and the failed
Stage361 Smoke. It launches no MATLAB, OpenFOAM, WSL, or CFD process.

The retained displacement and moved `polyMesh/points` are numerically
consistent (maximum reconstruction error below `1e-12 m`). The first restart
motion update nevertheless compresses the smallest mesh edge by more than a
factor of two in every slice, and the recorded Courant maximum reaches
`674.348` in slice 0000. The cylinder `U` boundary is also serialized as
`uniform (0 0 0)` after the update, whereas the saved source uses the evaluated
nonuniform moving-wall values.

Therefore Stage361 is a mesh-motion/restart-generation failure, not evidence
of physical VIV instability and not a simple stale `phi/meshPhi/Uf` problem.
The repair must generate a restart from a genuinely completed OpenFOAM time
step or otherwise rebuild the dynamic-mesh state consistently. This report
does not authorize a CFD retry.

Gate: `STAGE4F_D_RESTART_MESH_QUALITY_AUDIT_V1_GATE: pass`
