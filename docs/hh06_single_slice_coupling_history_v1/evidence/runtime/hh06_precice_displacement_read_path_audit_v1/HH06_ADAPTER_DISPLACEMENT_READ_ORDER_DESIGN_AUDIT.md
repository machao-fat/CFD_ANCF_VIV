# HH06 Adapter Displacement Read Order Design Audit

## 1. Scope and execution boundary

This is a source-only design audit for the HH06 single-slice OpenFOAM–preCICE–ANCF path. No adapter source, OpenFOAM case, XML, solver setting, or physical parameter was modified. No compilation, preCICE initialization, OpenFOAM solve, 50-window run, or production FSI run was performed.

The audited adapter source is the isolated source snapshot under:

`D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\hh06_precice_displacement_read_path_audit_v1\diagnostic_adapter_source`

The OpenFOAM lifecycle was checked against the installed OpenFOAM 10 source under:

`\\wsl.localhost\Ubuntu-22.04\opt\openfoam10`

The previously qualified, source-pinned time-layer implementation was used only as corroborating local evidence:

`D:\研二文件\开题准备\CFD_ANCF_VIV\tools\reproducible_openfoam10_adapter_rollback_qualification_v1\patches\0005-precice-time-layer-and-different-input-rollback.patch`

`D:\研二文件\开题准备\CFD_ANCF_VIV\docs\precice_time_layer_contract_and_different_input_rollback_closure_v1\PRECICE_TIME_LAYER_CONTRACT_AND_DIFFERENT_INPUT_ROLLBACK_CLOSURE_V1_REPORT.md`

## 2. Executive decision

`Adapter::readCouplingData()` must satisfy the following invariant:

> The displacement sample for the next tentative fluid solve must be read after preCICE `advance()`, after any required fluid checkpoint restore/write action, and before the next OpenFOAM fluid solve begins.

For the choices in the task:

- The semantic answer is **D: before the next fluid solve**.
- Its concrete location in `Adapter::execute()` is **after B (`advance`) and, when rollback is requested, after C (`readCheckpoint`)**.
- It must not be inserted immediately after `advance()` but before `readCheckpoint()`, because rollback would overwrite the newly read displacement.
- C alone is not sufficient because a new displacement is also required when a window completes without rollback and the next window begins.
- A is incorrect for this lifecycle because the new structure sample is not available to the Fluid participant until the coupling exchange performed by `advance()`.

For the frozen HH06 fixed-step, non-subcycled contract, the execute-path read time is:

`readCouplingData(precice_->getMaxTimeStepSize())`

The initialization path is a separate mandatory case:

`precice_->initialize()` followed by `readCouplingData(0.0)`

This initialization read is required before the first fluid solve. Adding only the execute-path read would leave the first solve with the existing zero `pointDisplacement`/`cellDisplacement` fields.

## 3. Current `Adapter::execute()` sequence

The current source explicitly states that `Adapter::execute()` runs after OpenFOAM has solved the current timestep (`Adapter.C:602-603`). Its actual sequence is:

1. `writeCouplingData()` (`Adapter.C:611`)
2. `advance()` (`Adapter.C:615`)
3. conditional `readCheckpoint()` (`Adapter.C:617-622`)
4. conditional `writeCheckpoint()` (`Adapter.C:624-628`)
5. optional rewriting of completed-window results (`Adapter.C:630-652`)
6. `adjustSolverTimeStepAndReadData()` for a fixed timestep (`Adapter.C:654-663`)
7. finalization if coupling has ended (`Adapter.C:665-687`)

There is no call to `Adapter::readCouplingData()` in this sequence.

### 3.1 `writeCouplingData()`

`Adapter::writeCouplingData()` iterates over configured interfaces and calls `Interface::writeCouplingData()`. The interface writers gather the current OpenFOAM-side coupling quantity (HH06: integrated `Force`) into the interface buffer and call preCICE `writeData`.

In lifecycle terms, this publishes the result of the fluid solve that has just completed.

### 3.2 `advance()`

`Adapter::advance()` calls:

`precice_->advance(timestepSolver_)`

This completes the current coupling exchange, updates the preCICE coupling state, makes the next mapped structure input available, and may request a fluid checkpoint restore or a new checkpoint.

### 3.3 `readCheckpoint()`

When `requiresReadingCheckpoint()` is true, the adapter restores the beginning-of-window fluid state. The current implementation restores at least:

- OpenFOAM time/time index;
- mesh points for FSI;
- registered volume, surface, and point fields and their stored history levels.

This action must precede the new displacement read. Otherwise, a read performed immediately after `advance()` would be overwritten by the restored copies.

### 3.4 `writeCheckpoint()`

When `requiresWritingCheckpoint()` is true, the adapter snapshots the physical fluid state that must be recoverable during later implicit retries. The existing order is `readCheckpoint` first, then `writeCheckpoint`.

The new input read should remain after this checkpoint action. This keeps the rollback snapshot tied to the physical window state and makes every tentative input an explicitly reapplied coupling input after restoration.

### 3.5 `adjustSolverTimeStepAndReadData()`

Despite its name, the audited implementation does **not** read coupling data. It only:

- obtains the OpenFOAM-determined timestep;
- compares it with `precice_->getMaxTimeStepSize()`;
- sets `timestepSolver_`;
- updates OpenFOAM `deltaT` through `setDeltaTNoAdjust()`.

Therefore, this method name currently hides the missing input update; it cannot be treated as evidence that Displacement was read.

## 4. Correct parallel-implicit time-layer order

### 4.1 Initialization

The current `Adapter::initialize()` performs optional initial outgoing-data write, then `precice_->initialize()`, but it does not transfer the mapped input buffer into OpenFOAM fields.

The required initial order is:

1. register meshes/readers/writers;
2. write required initial outgoing data, if requested by preCICE;
3. `precice_->initialize()`;
4. `readCouplingData(0.0)`;
5. set up and write the first fluid checkpoint, if requested;
6. set the first solver timestep;
7. begin the first fluid solve.

Here `0.0` denotes the window-start initial sample.

### 4.2 Every completed fluid trial

The required execute order is:

1. current fluid trial has finished;
2. `writeCouplingData()` — publish current `Force`;
3. `advance()` — perform the coupling exchange;
4. if requested, `readCheckpoint()` — restore the physical window-start fluid state;
5. if requested, `writeCheckpoint()` — establish the next active window checkpoint;
6. if coupling remains ongoing, `readCouplingData(precice_->getMaxTimeStepSize())` — apply the next tentative/end-of-window `Displacement` sample to OpenFOAM displacement fields;
7. adjust `deltaT`;
8. return to OpenFOAM;
9. before the next fluid equations are solved, OpenFOAM performs its normal dynamic-mesh lifecycle and consumes the updated displacement fields.

For this non-subcycled HH06 contract, the post-`advance()` sample is the end of the coupling interval, so `getMaxTimeStepSize()` is the correct relative read time. Reading `0.0` at this point would reuse the window-start value and can contaminate a different-input implicit retry.

### 4.3 Why the four candidate positions differ

| Candidate | Decision | Reason |
| --- | --- | --- |
| A. before `advance()` | Reject | The new mapped structure input has not yet been exchanged. It reads the old coupling state. |
| B. immediately after `advance()` | Incomplete/unsafe as written | The input is available, but a following `readCheckpoint()` would erase the field update. |
| C. after rollback | Necessary on retry, but not sufficient alone | Correct for a rejected trial, but does not cover accepted-window transition or initialization. |
| D. before the next fluid solve | **Required invariant** | This is the only placement that covers normal advance and retries. In code it is implemented after `advance()` and after all checkpoint actions. |

## 5. What `FSI::Displacement::read()` actually does

`FSI::Displacement::read()` (`FSI/Displacement.C:94-141`) is a data-to-field operation only.

For `faceCenters` it:

1. copies the received preCICE buffer into the coupled patch of `cellDisplacement`;
2. interpolates that patch field to the coupled patch of `pointDisplacement`.

For `faceNodes` it writes the received values directly to the coupled `pointDisplacement` patch.

It does **not** call any of the following:

- `mesh.update()`;
- `mesh.move()`;
- `motionSolver::solve()`;
- `movePoints()`;
- `phi` correction;
- `meshPhi` creation or update.

Therefore, a successful `preCICE::Participant::readData()` is not sufficient by itself. The buffer must also reach `FSI::Displacement::read()`, and the normal OpenFOAM mesh-motion stage must subsequently run.

## 6. Dynamic-mesh trigger chain

The mesh-motion trigger belongs to OpenFOAM `pimpleFoam`, not to `FSI::Displacement::read()`.

For the installed OpenFOAM 10 source:

1. `pimpleFoam.C:86` calls `fvModels.preUpdateMesh()`.
2. `pimpleFoam.C:89` calls `mesh.update()` for topology change/mapping maintenance.
3. At the first PIMPLE iteration (or every outer corrector when configured), `pimpleFoam.C:101` calls `mesh.move()`.
4. `fvMesh::move()` calls the configured mesh mover's `update()` (`fvMesh.C:625-638`).
5. The `motionSolver` mesh mover calls `motionPtr_->newPoints()` and then `mesh().movePoints(...)` (`fvMeshMoversMotionSolver.C:66-70`).
6. `motionSolver::newPoints()` calls `solve()` before returning the current points (`motionSolver.C:115-119`).
7. For HH06 `displacementLaplacian`, `solve()` updates boundary coefficients and solves the Laplacian equation for `cellDisplacement` (`displacementLaplacianFvMotionSolver.C:223-240`).
8. `fvMesh::movePoints()` moves the polyMesh, computes swept-volume mesh flux, and creates/updates `meshPhi` (`fvMesh.C:1065-1147`). It also updates geometry, boundary/interpolation objects, and function-object move callbacks.

Thus the intended causal chain is:

`preCICE readData` → `FSI::Displacement::read` → updated `pointDisplacement/cellDisplacement` → return from adapter → next `pimpleFoam` mesh stage → `motionSolver::solve` → `fvMesh::movePoints` → `points/meshPhi/geometry` update → fluid solve.

No extra `mesh.move()` or `movePoints()` call should be inserted into `FSI::Displacement::read()`. Doing so would move the mesh inside the coupling callback and then allow `pimpleFoam` to move it again, creating a time-layer and double-motion risk.

## 7. Minimal modification design — not implemented

Only one production source file needs call-site changes:

### File

`Adapter.C`

### Function 1

`preciceAdapter::Adapter::initialize()`

### Insertion point

Immediately after:

`precice_->initialize();`

and before the first checkpoint and first fluid solve.

### Required call

`readCouplingData(0.0);`

### Function 2

`preciceAdapter::Adapter::execute()`

### Insertion point

After:

- `advance()`;
- conditional `readCheckpoint()`;
- conditional `writeCheckpoint()`;

and before timestep adjustment, return to the solver, and the next fluid solve.

### Required guarded call

`if (isCouplingOngoing()) readCouplingData(precice_->getMaxTimeStepSize());`

### Final intended call order

`fluid solve → write Force → advance preCICE → restore/write checkpoint as requested → read Displacement → adjust dt → OpenFOAM mesh motion → next fluid solve`

No changes are required by this design in:

- `Interface.C`;
- `FSI/Displacement.C`;
- `FSI/FSI.C`;
- `precice-config.xml`;
- `dynamicMeshDict`;
- `pimpleFoam`;
- ANCF worker/SHM1 code.

## 8. Final design-audit status

`HH06_ADAPTER_DISPLACEMENT_READ_ORDER_DESIGN_AUDIT = PASS`

Root cause of the observed zero motion is consistent with the source: Displacement is registered and the read implementation exists, but neither initialization nor the execute lifecycle transfers the received preCICE input into the OpenFOAM displacement fields.

The approved design is now precise enough for a separate, explicitly authorized implementation phase. This audit did not implement or run it.

Execution boundary confirmation:

- `NO_CODE_MODIFICATION = true`
- `NO_REBUILD = true`
- `NO_OPENFOAM_RUN = true`
- `NO_PRECICE_RUN = true`
- `NO_50_WINDOW_RUN = true`
- `NO_PRODUCTION_FSI = true`
- `NO_XML_CHANGE = true`
- `NO_SOLVER_PARAMETER_CHANGE = true`
