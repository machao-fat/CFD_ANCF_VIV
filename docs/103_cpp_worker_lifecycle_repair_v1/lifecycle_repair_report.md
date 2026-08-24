# C++ worker lifecycle repair audit

The coordinator and resident C++ adapter now share one lifecycle boundary.

- Offline tests: 33, return code: 0
- compileall: pass
- worker starts per segment: 1
- slice starts: 1, 1, 1; barrier release requires all three
- duplicate start: fail-closed; stop: idempotent and owned-only
- MATLAB/OpenFOAM/WSL/CFD starts: 0/0/0/0
- owned residual: 0
- C++ 40-step mock: pass; 40/40 physical committed and 40/40 fully audited
- persistent IPC regression: 15/15 passed
- root unittest: 1078 passed, 1 skipped, 0 failure/error (1079 collected)
- Release kernel selftest: pass

This is an offline lifecycle repair only. The real C++ bounded confirm remains not completed, and no OpenFOAM/WSL/CFD authorization was consumed.

The MATLAB/C++ numerical-core status remains `not_completed`: transport and
engineering-tolerance dual-run evidence exist, but strict numerical identity
has not been established. The staging Gate therefore remains
`STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_STAGING_V1_GATE: do_not_pass` until a
deployable `libancfFileMotion.so` and explicit OpenFOAM/WSL/CFD authorization
are available.
