# Continuation motion-clock forensic

Gate: `STAGE4F_D_CPP_WORKER_MOTION_CLOCK_FORENSIC_V1_GATE: pass`

The failed `confirm_015` runtime started OpenFOAM at `2.2575 s`, but the
ancfFileMotion dictionary still declared `startTime=2.2075 s`. The reader
therefore computed bridge step 40 while the continuation seed correctly
published bridge step 0, and the seed acknowledgement could never match.

The repair is isolated to a fresh template: all three `dynamicMeshDict` files
now use `startTime=2.2575` and retain the unchanged `couplingDeltaT=0.00125`.
The new `confirm_016` entry targets only step600--639 and has not been run.
Compile and four offline mapping/motion-clock tests pass; no real process was
started by this repair. A new explicit authorization is required before the
next real segment.
