# HH06 preCICE Handshake Qualification

**Classification:** `DO_NOT_PASS`

## Scope and boundary

The authorized test attempted one HH06 single-slice coupling window only. It did not call `launch.sh`; the Structure wrapper was bounded with `max_windows=1`, and the Fluid process was terminated immediately after the Structure process returned. No OpenFOAM physical step completed, no preCICE window was accepted, no ANCF advance was reached, and no new OpenFOAM time directory was created.

## Frozen identities

- Case: `/home/machao/OpenFOAM/coupling/singal_slice/slice0000`
- Structure participant: `Structure_0000`
- Fluid participant: `Fluid_0000`
- Coupling scheme: `parallel-implicit`
- Requested window: `dt = 0.0002 s`
- Worker: `/home/machao/OpenFOAM/coupling/singal_slice/slice0000/cfd_ancf_ancf_kernel_worker_shm1_qualified`
- Worker SHA256: `69f045eb7f4576e5178d10711f0f265d7458282a7a4ecbcb860a913ada45beef`
- Worker size: `2,647,128` bytes
- preCICE Python package: `3.4.0`; runtime library reported `3.4.1`

## Contract audit

The XML parsed and declares the intended interface:

- `Fluid_0000` writes `Force` on `Fluid-Mesh` and reads `Displacement`.
- `Structure_0000` writes `Displacement` on `Structure-Mesh` and reads `Force`.
- `Fluid-Mesh` is the 200-face-center mesh; `Structure-Mesh` has one coupling point.
- The XML uses conservative Force mapping and consistent Displacement mapping.
- The force path remains wall integration → resultant Force → one structural coupling point → ANCF generalized load; no CFD-face-to-ANCF-node mapping is used.

The qualified worker identity and the HH06 SHM1 model were not reached by this live test because initialization stopped before a model payload was sent.

## Execution evidence

### Phase 1 — initialization

**Failed.** preCICE rejected `Structure_0000.initialize()` with:

> Initial data has to be written to preCICE before calling initialize(). After defining your mesh, call requiresInitialData() to check if the participant is required to write initial data using the writeData() function.

The XML explicitly contains `initialize="yes"` for the initial `Displacement` exchange. The current `PreciceStructureFleetBackend.initialize()` defines the mesh and calls `initialize()` without first checking `requires_initial_data()` and writing the zero absolute displacement.

### Phase 2 — one-window data exchange

Not reached. No accepted coupling window, Force read, Structure advance, or Displacement write was recorded.

### Phase 3 — checkpoint/rollback

Not reached. There was no preCICE iteration or checkpoint request. The previously qualified offline physical rollback and transport-ID behavior were not re-used as evidence of a live preCICE handshake.

## Process and time-directory evidence

- Structure return code: `1` (preCICE initialization exception).
- Fluid return code: `143` after controlled termination when Structure exited; it had only created the mesh at existing time `30`.
- No surviving `pimpleFoam`, Structure, or worker process.
- Case directories after the attempt: `30`, `constant`, `system`, `precice-sockets`; no `30.0002` or other new physical time directory.
- The raw participant and Fluid stdout/stderr are retained as `HH06_HANDSHAKE_PARTICIPANT.*` and `HH06_HANDSHAKE_FLUID.*` in the case directory.

## Primary blocker

`PRECICE_INITIAL_DATA_NOT_WRITTEN_BEFORE_INITIALIZE`

This is a protocol/lifecycle defect in the current Structure-side backend path, not a CFD, worker, SHM1, force-normalization, or physical-parameter failure. The minimum corrective action is to make the Structure participant, after defining `Structure-Mesh`, call `requires_initial_data()` and, when required, write the initial absolute displacement `(0, 0)` at the one coupling point before `initialize()`. The XML should remain unchanged because it correctly requests initial displacement exchange. No such correction was made in this qualification run.

## Final decision

`HH06_PRECICE_HANDSHAKE_QUALIFICATION = DO_NOT_PASS`

No authorization for a 0.2 s production FSI run is implied. The next action should be a separately authorized wrapper/backend lifecycle fix followed by this same one-window qualification.

