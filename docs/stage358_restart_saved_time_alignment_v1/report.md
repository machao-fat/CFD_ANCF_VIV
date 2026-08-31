# Stage 358 saved-time restart alignment

Stage358 treats the Stage341 `80` directory as the actual saved state at
79.995 s. It relabels the complete field set, including binary field headers
and `uniform/time`, to 79.995 s and binds the lag-1 structure state to that
same clock. The candidate is generated offline only; it does not launch any
MATLAB, OpenFOAM, WSL, or CFD process. A new explicit Smoke authorization is
required before using it.
