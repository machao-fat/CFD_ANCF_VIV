# Stage 220 C++ worker to 70 s offline integration

- Gate: `STAGE4F_D_CPP_WORKER_TO70S_INTEGRATION_V1_GATE: pass`
- This is a 120-step three-slice simulation of the 0 s to 70 s contract; the 56,000-step target is not executed.
- Commits/barriers/acks: 120/120/360.
- Retention: case entries per slice=[41, 41, 41]; checkpoints=40; exchange artifacts=40.
- Mock worker/slice startup is recorded for lifecycle coverage; real MATLAB/OpenFOAM/WSL/CFD starts are all zero.
- Compileall passed; the joint Stage 219 + Stage 220 offline regression passed (`11 tests`, `0 failures`, `0 errors`).
- An already-running Windows `wslservice` was observed but was not started, owned, or managed by this stage.
- Read-only real-start preflight is `do_not_start`: the previously cleaned worker executable, `libancfFileMotion.so`, and 30 s runtime are absent. Fresh artifacts must be rebuilt and hashed before any real-run request.
- The integration Gate qualifies sequencing and storage only. A fresh explicit authorization is still required before a real campaign.
