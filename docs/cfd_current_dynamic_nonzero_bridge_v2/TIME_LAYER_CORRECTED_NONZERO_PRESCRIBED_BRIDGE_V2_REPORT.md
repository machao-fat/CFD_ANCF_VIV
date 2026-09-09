# Current production CFD non-zero prescribed-motion bridge V2

## Scope and immutable context

This is the one authorized, bounded implementation bridge.  It is a paired
OpenFOAM calculation from OF 0.105 to 0.605 s (100 steps of 0.005 s), without
ANCF or free feedback.  Both cases use the legal dynamic restart state,
expanded-medium mesh, frozen fluid properties, `fvSchemes`, `fvSolution`, and
the same raised-cosine-started motion

`y(t)=0.1 r(t-0.105) sin(2 pi 0.16 (t-0.105)) m`.

The only physical implementation difference is the internal mesh-motion path:

| Reference | Current path |
|---|---|
| native OF10 `interpolatingSolidBody` / `sixDoFMotion` table | real preCICE Adapter / `pointDisplacement` / `displacementLaplacian` |

It does not change the production Adapter, OF10-owned restore implementation,
mesh, PIMPLE, time step, fluid properties, mapping, or the motion formula.  It
does not validate free FSI, VIV physics, or the failed three-slice 0.05 s run.

V1 remains immutable:

```
NONZERO_PRESCRIBED_BRIDGE_V1 = FAIL_CLOSED
MESH_METHOD_FORCE_COMPARISON_V1 = NOT_EVALUABLE
```

Its failure was a test-participant time-layer mismatch, not a force-method
conclusion.

## Time-layer audit and V2-only correction

The actual binary source and immutable V1 events establish the following:

* preCICE is version 3.4.1; the XML uses `parallel-explicit`, non-subcycled
  exchange, not a serial or implicit scheme.
* `Adapter::initialize()` calls `readCouplingData(0.0)`.
* after every solved CFD step, `Adapter::execute()` calls
  `readCouplingData(getMaxTimeStepSize())` for the next window.
* V1 supplied initial `y(0.105)`.  Its recorded geometry therefore showed a
  uniform one-step lag: CFD output `.110` applied `y(.105)`, and output `.605`
  applied `y(.600)`.

V2 changes only the test participant's *preCICE storage-layer schedule*.  It
does not phase-shift the formula:

| CFD output | V2 storage source | Applied frozen sample |
|---|---|---|
| OF 0.110 s | initial data before `initialize()` | `y(0.110) = 3.0942444691867773e-6 m` |
| OF 0.115 ... 0.605 s | write before participant advances 1 ... 99 | matching `y(t_n)` |
| after OF 0.605 s | required final preCICE write | duplicate `y(.605)`; no subsequent CFD output consumes it |

The pre-execution table contains all 100 mappings and passed before launching
CFD.  It is recorded in
`runtime/cfd_current_dynamic_nonzero_bridge_v2_run_001/time_layer_preflight.json`.
The participant event trace separately labels preCICE storage time and the CFD
output time; it does not label a stored payload as a different physical motion
time.

## Binary identity and execution evidence

The independent owner-diagnostic ABI prefix was used throughout.  `ldd -r`
reported neither unresolved symbols nor `/opt/openfoam10` dependencies.

| Component | identity |
|---|---|
| `pimpleFoam` | `/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam`; SHA256 `c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43` |
| Adapter | `/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/adapter_owner_diagnostic_build_001/lib/libpreciceAdapterFunctionObject.so`; SHA256 `c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17` |
| OF core dependencies | `libOpenFOAM.so` and `libfiniteVolume.so` both resolve from the same `owner_diagnostic_abi_build_001` prefix |

The one authorized pair completed with `native=0 structure=0 fluid=0`.
The host command wrapper returned before writing its own
`launcher_return.json`, but it did not terminate the WSL processes; the
immutable `returns.txt`, full stdout/stderr, 100 output directories, and
participant evidence are the execution evidence.  This is a launcher-record
limitation, not a numerical retry and no second run was made.

## Motion identity: PASS

The predeclared hard motion tolerance is `1e-9 m`.  At every one of 100 output
times, all 80 unique cylinder boundary vertices were compared to the frozen
output-time displacement.  For the current Adapter path, all 80
`pointDisplacement` cylinder values were also compared component-by-component.

| time | native boundary max error | Adapter boundary max error | Adapter `pointDisplacement` max error |
|---|---:|---:|---:|
| 0.110 s | `4.6924e-13 m` | `4.6924e-13 m` | `3.2225e-18 m` |
| 0.605 s | `1.7158e-13 m` | `1.7158e-13 m` | `2.8470e-14 m` |

All intermediate outputs satisfy the same condition.  The first participant
force read corresponds to output `.110` and records expected plan step 1; the
last read corresponds to `.605` and expected plan step 100.  Thus V2 is not
the V1 one-step-lag comparison.

```
NONZERO_PRESCRIBED_BRIDGE_V2_MOTION_IDENTITY = PASS
MESH_METHOD_FORCE_COMPARISON_V2 = EVALUABLE_FOR_BOUNDED_SCOPE
```

## Fluid, force, and mesh observations

Both solvers ended normally with no FPE, negative-volume, or other hard log
marker.  All 100 time directories contain `meshPhi`.  Maximum Courant number
was `0.35010195544` for both paths; maximum absolute global continuity error
was `7.33780069821e-11` (native) and `1.09696197996e-10` (Adapter), below the
frozen `1e-8` limit.

Once motion identity passed, the predeclared force comparison became
interpretable.  The existing 15% relative-L2 value remains reporting-only; it
was not changed into an after-the-fact pass criterion.

| total force component | relative L2 difference | maximum absolute difference |
|---|---:|---:|
| Fx | `2.589866e-4` | `0.870431 N` |
| Fy | `1.163411e-3` | `2.607938 N` |

Pressure and viscous components were retained in the result JSON.  These
small bounded-run differences are consistent with two legitimate interior mesh
deformations, but are not a multi-cycle physical validation.

`checkMesh` reports the Adapter final mesh as `Mesh OK` (minimum determinant
`0.53056941246`, maximum non-orthogonality `31.3640419872`, maximum skewness
`0.503054953946`).  The native final mesh has the previously known two-
dimensional prism diagnostic: 47 edges are not aligned with the non-empty
directions, so `checkMesh` reports one failed geometry check.  Its core volume,
non-orthogonality, skewness, face, and determinant checks pass (minimum volume
`0.00159110782241`, determinant `0.529906856573`).  This native-only geometry
warning is recorded rather than converted into a hidden Adapter failure.

## Interpretation and next decision

This closes only the bounded, non-zero prescribed-motion implementation bridge
for the current configuration.  It shows that, after correcting the
test-participant data-layer schedule, the real preCICE/Adapter path applies the
same complete cylinder boundary motion as the native reference and yields a
small reported force difference over this 0.5 s interval.

It does **not** establish the cause of the three-slice force-growth problem,
does not change W10 replay evidence, and does not reclassify any historical
failure.  In particular, the test-participant V1 lag is not evidence that the
production three-slice Adapter exchange had the same defect.

The appropriate next human decision is whether to design an independent,
physically specified single-slice free-FSI benchmark, after retaining the
fixed-cylinder and ANCF foundation-validation work.  No such run is started by
this result.

```
LOCAL_FIXED_ZERO_BRIDGE = FAIL_CLOSED                 # immutable historical gate
ZERO_MOTION_INITIAL_FLUX_CAUSE = SUPPORTED_BY_COUNTERFACTUAL
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

## Reproducibility index

* Tool: `tools/cfd_current_dynamic_nonzero_bridge_v2/run_bridge_v2.py` — SHA256
  `8ef9a109f81bed9c0b8cedf5e20bfd0f80f2ce9887ee6a46aecac3895acfc939`.
* Runtime manifest SHA256:
  `e28d2e83e4f050460b9c3a1f91c6ab3b0aa4e1724374bc517bf0bbc805726e69`.
* Time-layer preflight SHA256:
  `2963e7ff7ca9d33db2758c6ffa86f4d1c0eb436565cbf0692b68977cd0c0fc33`.
* Result SHA256: `3943b6d68330f5aaffab28800ee0d5a7a5068268635abbbf526903dbcc471603`.
* Runtime: `runtime/cfd_current_dynamic_nonzero_bridge_v2_run_001`.
* Result: `results/cfd_current_dynamic_nonzero_bridge_v2_run_001/bridge_result_v2.json`.
