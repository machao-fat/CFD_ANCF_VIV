# HH06 Single-Slice FSI Preproduction — 50-Window Qualification

**Classification:** `DO_NOT_PASS`

## Requested scope

- Restart field: global OpenFOAM time `30 s`
- Coupling step: `0.0002 s`
- Requested accepted windows: `50`
- Requested target end: `30.01 s`
- Participants: `Fluid_0000` and `Structure_0000`
- Scheme: `parallel-implicit`, minimum 2 and maximum 8 iterations

`launch.sh` was not used. No contract, XML, OpenFOAM case, mesh, worker, SHM1 protocol, or physical parameter was changed.

## Actual result

The real Fluid–Structure pair initialized successfully and completed **two** accepted coupling windows:

1. `30.0000 -> 30.0002 s`
2. `30.0002 -> 30.0004 s`

The third physical window reached a non-converged implicit retry sequence but did not commit. The run then stopped with:

```text
CheckpointError: no active checkpoint
```

Therefore the 50-window target and `30.01 s` target were not reached.

## Root cause

`GenericStructuralCoordinator.rollback()` consumes the active checkpoint by setting its checkpoint handle to `None`. During the third parallel-implicit window, preCICE requested another rollback after an earlier retry. The wrapper did not establish a new active coordinator checkpoint for that repeated retry, so the second rollback failed closed with `CheckpointError: no active checkpoint`.

This is a checkpoint lifecycle/rollback orchestration defect. It is not evidence of an SHM1 parse error, worker duplicate-ID error, CFD fatal error, negative volume, or physical-parameter problem.

The failure occurred in the Structure participant before the third window could be accepted. No automatic repair or retry was performed.

## Evidence

- Structure return code: `1`.
- Fluid return code: `143`, controlled termination after Structure failure.
- preCICE `Time window completed` records: `2`.
- Structure log shows windows 1 and 2 complete, then window 3 iterations 1–3 followed by the checkpoint exception.
- No duplicate request/transaction/sequence-ID signature was observed.
- No FPE, NaN/Inf, negative-volume, solver-fatal, or preCICE max-iteration failure signature was observed before the checkpoint exception.
- Fluid Co values remained small: initial mean `0.01601199855`, initial max `0.4182184878`; subsequent max values shown were below `0.419`.
- Largest displayed local continuity residual during the attempted windows was approximately `8.15e-09`; global residuals remained at approximately `1e-10` scale.
- No new physical OpenFOAM time directory was written. The case retained restart directory `30`; only runtime `postProcessing`, profiling, and socket evidence directories exist.

## SHM1 and worker status

The qualified worker was started and accepted the HH06 SHM1 model far enough to perform the first physical advances; no SHM1 downgrade or worker protocol error was reported.

- Worker SHA256: `69f045eb7f4576e5178d10711f0f265d7458282a7a4ecbcb860a913ada45beef`
- Structure/Fluid mesh contract: 1 structural coupling point and 200 fluid face-center vertices.
- Force/Displacement mappings initialized successfully.

## Preserved raw evidence

The following files remain in the case directory:

- `HH06_50W_PARTICIPANT.stdout`
- `HH06_50W_PARTICIPANT.stderr`
- `HH06_50W_FLUID.stdout`
- `HH06_50W_FLUID.stderr`
- `HH06_50W_RESULT_RAW.json`
- `HH06_50W_STATUS.txt`

No long-time FSI continuation was started after the failure.

## Final decision

`HH06_SINGLE_SLICE_FSI_PREPRODUCTION_50WINDOW = DO_NOT_PASS`

The minimum next action is an explicitly authorized checkpoint-lifecycle repair so that one physical checkpoint remains available for every preCICE rollback retry within a window, followed by a fresh bounded qualification. This run must not be treated as a 50-window stability result.

