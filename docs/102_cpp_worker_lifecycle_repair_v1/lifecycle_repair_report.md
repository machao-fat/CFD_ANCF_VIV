# C++ worker lifecycle repair audit

The coordinator and resident C++ adapter now share one lifecycle boundary.

- Offline tests: 32, return code: 0
- compileall: pass
- worker starts per segment: 1
- slice starts: 1, 1, 1; barrier release requires all three
- duplicate start: fail-closed; stop: idempotent and owned-only
- MATLAB/OpenFOAM/WSL/CFD starts: 0/0/0/0
- owned residual: 0

This is an offline lifecycle repair only. The real C++ bounded confirm remains not completed, and no OpenFOAM/WSL/CFD authorization was consumed.
