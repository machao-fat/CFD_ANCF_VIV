# Stage343: 80 s to 200 s continuation

- Source: Stage341 `global_step=16000`, `time=80.0 s`.
- Target: `global_step=40000`, `time=200.0 s`.
- Advance: `24000` steps at `dt=0.005 s`.
- Three OpenFOAM 10 slices with preCICE 3.4.1 and the C++ worker.
- A fresh runtime is mandatory. Stage341 remains read-only.
- Each slice retains only the latest numerical time (`purgeWrite=1`), the
  restart state, compact quality JSON, checkpoints, and scalar convergence
  evidence. Raw OpenFOAM stdout is not retained.
- The run does not change formal statistical thresholds or claim convergence
  automatically. A new Gate is required after completion.
