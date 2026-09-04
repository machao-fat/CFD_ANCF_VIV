# Stage 377: Fresh Three-Slice Observability Confirmation

This authorized run is a fresh `0 -> 0.2 s` three-slice window with 40 steps,
`dt=0.005 s`, OpenFOAM 10, preCICE 3.x, and one persistent C++ worker. It is
an observability confirmation, not a formal VIV convergence run.

Gate:

```text
STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_OBSERVABILITY_040S_V1_GATE: pass
```

The run proved:

* all 40 structure steps committed and all three slices have 40 records;
* global step, local bridge step, time/tick, barrier and terminal time agree;
* every slice has 40 finite OpenFOAM quality records, including terminal
  `courant_max`;
* structure, three fluids and C++ worker returned zero and cleaned up;
* only compact logs/checkpoint and latest binary fields were retained.

Stage 375 is retained as a separate `do_not_pass` failure record. Its
fresh-start `pointDisplacement` registry failure was fixed by using
`namePointDisplacement unused`; Stage 376 then proved that fix but used the
old v1 quality parser, which missed the terminal Courant field. Stage 377 uses
the strict pending-Courant parser and is the passing confirmation.

This Gate does not change formal statuses and does not authorize a longer CFD
run. A separate explicit authorization is required for any larger window.
