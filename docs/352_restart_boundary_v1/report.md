# Stage352 restart boundary repair

Stage349-351 showed that the saved `80` field carries a cylinder displacement
boundary matching diagnostic step `15999` (`79.995 s`) while the field metadata
is `80 s`. Stage352 creates a fresh candidate by copying the source field and
patching only the copied `pointDisplacement` and `cellDisplacement` cylinder
boundary entries to the finalized step-16000 interface positions.

The patch is performed in pure Python over the OpenFOAM binary layout; no WSL,
OpenFOAM, MATLAB, or CFD process is started. The source runtime remains
read-only. A fresh real Smoke is still required before any continuation can be
considered.
