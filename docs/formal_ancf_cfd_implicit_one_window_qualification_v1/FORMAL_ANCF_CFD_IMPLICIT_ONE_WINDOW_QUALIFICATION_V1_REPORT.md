# Formal ANCF--CFD Implicit One-Window Qualification V1

## Result

`FORMAL_IMPLICIT_ONE_WINDOW = FAIL`.

The sole authorized fresh runtime is immutable:
`runtime/formal_ancf_cfd_implicit_one_window_qualification_v1_run_001`.
It did not reach a CFD physical solve, a preCICE checkpoint callback, an
implicit trial, or a physical commit. No retry was performed.

## Production integration preflight

All three generated Fluid cases passed the shared moving-mesh contract. Each
case explicitly names the same absolute adapter library:

```
/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/
diagnostic_build_006/lib/libpreciceAdapterFunctionObject.so
```

Its SHA-256 is
`6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`.
The loaded library was built from upstream OpenFOAM10 commit
`d53753b1c927b2413b02299c9da15725b3e772f0` with patches 0001, 0002,
0004, and 0005; Foundation OpenFOAM 10 and preCICE 3.4.1 were frozen in the
runtime manifest. The precursor U/p/phi manifest checks, Quality V4 contract,
Generalized Force Metric V2 contract, and moving-mesh preflight were all
written before launch and passed.

The checkpoint-aware production Structure participant and the immutable
six-cycle rollback regression remained selected. No physical ANCF state was
advanced in this failed runtime; its C++ worker shut down cleanly with return
code zero and no owned residual.

## First blocker

`STRUCTURE_INITIAL_DATA_NOT_WRITTEN` is the first fail-closed gate.

The formal XML made the Displacement exchange `initialize="yes"`, while the
production Structure participant called `initialize()` before asking
`requiresInitialData()` and writing the zero initial total Displacement. The
actual preCICE 3.4.1 error was:

```
Initial data has to be written to preCICE before calling initialize().
```

This is an integration/fixture initialization omission, not a numerical
fixed-point convergence result and not an ANCF, force-contract, mapping, mesh,
or timestep result.

An independent secondary launcher defect was observed concurrently: the
OpenFOAM-generated XML contained a malformed socket exchange directory of the
form `/mnt//nt/d/...`. The WSL execution path was converted a second time by a
Windows-only helper inherited by this formal launcher. Each Fluid participant
therefore also aborted while attempting to create the socket directory. This
secondary defect does not change the first Structure initial-data blocker.

Both defects must be corrected in a separately authorized configuration-only
task, with a new runtime. This task did not apply either correction or repeat
the run.

## Gates not evaluable in this runtime

| Evidence | Status | Reason |
| --- | --- | --- |
| Coupling iterations | 0 | Structure initialization failed |
| Structure checkpoint / rollback | NOT_EVALUABLE | no preCICE window entered |
| Fluid U/p/phi/Uf/meshPhi rollback | NOT_EVALUABLE | Fluid initialization failed |
| Dynamic-mesh rollback | NOT_EVALUABLE | no mesh trial occurred |
| Time-layer runtime identity | NOT_EVALUABLE | no window entered; source contract remains frozen PASS |
| Raw Fx/Fy and integrated slice forces | NOT_AVAILABLE | no CFD solve or Force export |
| max ux/vx | NOT_AVAILABLE | no prediction/correction record |
| Quality V4 | NOT_EVALUABLE | no OpenFOAM time record |
| Generalized Force Metric V2 | NOT_EVALUABLE | no correction request |
| ANCF Newton | NOT_EVALUABLE | no prediction/correction record |

`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.

## Scope preservation

No 0.05 s, 0.1 s, 1 s, or longer case was launched. No dt, mesh, PIMPLE,
physical parameter, damping, force scaling, mapping, relaxation, Aitken, or
IQN setting changed. The old deployed adapter and all earlier runtimes remain
untouched.
