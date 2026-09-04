# Stage315 moving-mesh evidence repair

Stage314 completed a fresh 8-step, three-slice OpenFOAM 10/preCICE smoke with
zero return codes and a complete global barrier. It did not pass the moving
mesh gate: the latest `cellDisplacement`, `pointDisplacement`, and
`polyMesh/points` artifacts were unchanged, and all three force hashes were
identical. Therefore Stage314 is a failed runtime and is not reusable.

The evidence audit now requires all of the following before a new real run can
be requested:

- a non-zero `cellDisplacement` interface value;
- a changed latest mesh-point hash relative to the initial mesh;
- a compatible point-field boundary;
- distinct per-slice force hashes for every committed step;
- complete preCICE and C++ identity/barrier records.

The Stage304--314 runtimes and historical evidence remain protected. No
physical parameter, ANCF/EB core, global timestep, slice count, threshold, or
formal protocol is changed by this audit repair. A new explicit authorization
is required before any further real OpenFOAM/preCICE run.

## Offline gate

Run the audit without starting WSL or any solver:

```powershell
python tools/stage315_moving_mesh_evidence_repair_v1/run_offline_gate.py
```

The machine-readable result is written to
`results/315_moving_mesh_evidence_repair_v1/stage4f_d_moving_mesh_adapter_read_path_repair_v1_gate.json`.
Pass means only that one fresh, short moving-mesh three-slice smoke may be
requested. It is not permission to start that smoke or any longer CFD run.

The first authorized follow-up smoke (Stage316) failed closed because the
runtime generator used a `calculated` cylinder patch. OpenFOAM 10's adapter
reader performs a `refCast` to `Field`, so that patch type aborts. The generator
has been corrected to use `fixedValue`; Stage316 remains failed evidence and
must not be reused.
