# C++ Worker Offline Performance V1

The resident C++ worker processed the bounded 40-step fixture with one worker startup and no MATLAB/OpenFOAM/WSL/CFD process starts. Segment wall-clock was `0.0466255 s`; step mean/P50/P95 were `1.0665 ms / 0.9938 ms / 1.1551 ms`. IPC send/receive/decode mean was `0.9991 ms`; request encoding mean was `0.0490 ms`. The worker returned zero and owned residual was zero.

These values are an offline kernel/transport baseline only. They must not be presented as a CFD speedup relative to the 35--37 s MATLAB/OpenFOAM baseline until a new real three-slice confirm is completed.

`STAGE4F_D_CPP_WORKER_OFFLINE_PERFORMANCE_V1_GATE: pass`
