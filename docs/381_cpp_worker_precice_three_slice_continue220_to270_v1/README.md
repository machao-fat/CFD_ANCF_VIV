# Stage 381: 220--270 s continuation

This stage starts from the finalized Stage 379 220 s endpoint and uses a new
runtime, run id, and case id. It uses `dt=0.005 s`, three slices, OpenFOAM 10,
preCICE 3.x, and the persistent C++ worker. The source runtime remains read
only. `purgeWrite=1`, binary fields, and compact logs retain only the latest
restart fields plus scalar/checkpoint evidence.

The launcher performs a strict source check before starting. The final Gate
requires 10,000 committed steps, all three slice counts, complete per-step
quality records (`time_s`, `courant_max`, `residual_max`, `continuity_global`,
`iterations_max`), zero returns, final fields, and zero owned residual.

## Read-only progress check

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
powershell -ExecutionPolicy Bypass -File ".\tools\stage381_cpp_worker_precice_three_slice_continue220_to270_v1\get_stage381_status.ps1"
```

The run must not be restarted in the same runtime after a failure. Formal
statistics remain `not_completed` until a separate convergence audit passes.
