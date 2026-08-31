# Stage 353 restart boundary preparation

This offline repair creates a fresh candidate from the protected Stage341 80 s
fields. It aligns the cylinder boundary values in both `pointDisplacement` and
`cellDisplacement` with the global step 16000 / time 80.0 s interface positions.
The Stage352 failed candidate is not reused. The preparation tool does not start
MATLAB, OpenFOAM, WSL, or CFD and does not modify the Stage341 source runtime.

The generated machine-readable evidence and Gate are written under
`results/353_restart_boundary_v1`.
