# Stage 354 restart boundary preparation

Stage354 is a fresh offline candidate after parser failures in Stage352 and
Stage353. It copies the protected Stage341 80 s field, aligns the cylinder
boundaries in `pointDisplacement` and `cellDisplacement` to the global step
16000 / time 80.0 s interface positions, and records hashes and process counts.
No MATLAB, OpenFOAM, WSL, or CFD process is started. Protected source evidence
and failed candidates remain untouched.
