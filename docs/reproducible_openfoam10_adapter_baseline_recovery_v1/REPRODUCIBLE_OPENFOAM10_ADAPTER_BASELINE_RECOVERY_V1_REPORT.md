# REPRODUCIBLE_OPENFOAM10_ADAPTER_BASELINE_RECOVERY_V1

## Decision

| Gate | Status |
| --- | --- |
| `LEGACY_SOURCE_PROVENANCE` | `UNRECOVERED` |
| `REPRODUCIBLE_ADAPTER_BASELINE` | `PASS` |
| `OPENFOAM10_COMPATIBILITY` | `PASS` |
| `CHECKPOINT_SEMANTICS_AUDIT` | `NOT_COMPLETED` |
| `NONCOUPLED_REGRESSION` | `PASS` |
| `ROLLBACK_INSTRUMENTATION_READY` | `NO` |
| `NEXT_ONE_WINDOW_IMPLICIT` | `CONDITIONAL` |

No coupled CFD, ANCF worker, or historical runtime was started or modified.

## Legacy provenance recovery

The deployed legacy library remains immutable at
`/home/machao/OpenFOAM/stage315_adapter_build/libpreciceAdapterFunctionObject.so`.
Its SHA-256 is
`26ad8529822f96ca8ddfb3370f85257b0d19b56958538d6073cf8af897aac572` and
its ELF build-id is `e76f7d6491a2f32cf9d6d5712c79b1ce55cd862b`.

Read-only inspection found no source tree, worktree, `Make/options`, object
files, `Allwmake`, `wmake.log`, `ldd.log`, or build script under the actual
`stage315_adapter_build` directory. The only candidate (`3d45c38c…`) is a
v1.3.0 source candidate from `precice/openfoam-org-adapter`; its banner is not
provenance. Its old OpenFOAM include/library layout also fails against the
installed Foundation 10 environment. The legacy source therefore remains
unrecovered. This report does not reclassify or validate historical results.

## Selected reproducible baseline

The new baseline is the official `precice/openfoam-adapter` `OpenFOAM10`
branch at `d53753b1c927b2413b02299c9da15725b3e772f0` (`Various fixes for
OpenFOAM 10`). The downloaded source archive has SHA-256
`e3db4a1aa52b0e318117bbbe90336afd183b2105ed78fe527aea8436f3da4251`.

The only local patch is
`tools/reproducible_openfoam10_adapter_baseline_recovery_v1/patches/0001-respect-adapter-target-dir.patch`.
It lets the build select `ADAPTER_TARGET_DIR`; it changes only build output
placement, not adapter runtime semantics. The repeatable builder is
`tools/reproducible_openfoam10_adapter_baseline_recovery_v1/build_reproducible_openfoam10_adapter.sh`.

The OpenFOAM10 branch already contains the semantic port, rather than a local
header-only workaround:

- `Interface.C` uses `polygonTriangulate.H` and `polygonTriangulate` for
  connectivity.
- `preciceAdapterFunctionObject` implements the Foundation 10 pure virtual
  `fields()` method.
- `Make/options` and FSI force-model headers use the Foundation 10 transport
  and momentum-model interfaces.
- `setupMeshVolCheckpointing()` guards `V0` and `V00` with `foundObject`.

## Frozen build environment

The build shell is OpenFOAM Foundation 10, build `10-c4cf895ad8fa`, from
`/opt/openfoam10`, with `WM_OPTIONS=linux64GccDPInt32Opt`, `wmake` at
`/opt/openfoam10/wmake/wmake`, and GCC/G++ 11.4.0. `pkg-config` resolves
preCICE 3.4.1 as `-lprecice`; the produced library links `libprecice.so.3` and
the Foundation 10 OpenFOAM libraries from
`/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib`. The build Python shell
has no pyprecice binding, which is not an adapter-build dependency.

Per-build complete `LD_LIBRARY_PATH`, compiler flags, linker flags, dependency
and ELF-note outputs remain alongside each external build under
`/home/machao/OpenFOAM/reproducible_adapter_baseline_v1/build_{d,e}`.

## Clean builds and ABI audit

Two clean archive extractions and builds completed in independent directories.
Both produced byte-identical libraries:

`/home/machao/OpenFOAM/reproducible_adapter_baseline_v1/build_d/lib/libpreciceAdapterFunctionObject.so`

`/home/machao/OpenFOAM/reproducible_adapter_baseline_v1/build_e/lib/libpreciceAdapterFunctionObject.so`

Each has SHA-256
`5e5cb644a072c7eee87217f674b57a1421b66c13fc5817d1d51b684884350ede` and
ELF build-id `024b00833eb69048e2d48327f58cc0bf8d61043e`. `ldd -r` reported no
missing libraries or undefined symbols. The new library is intentionally not
the legacy SHA-256 and does not replace it.

## Non-coupled regression

Evidence is in
`results/reproducible_openfoam10_adapter_baseline_recovery_v1/noncoupled_regression.json`
and its separate runtime directory. It records:

- a zero-motion dynamic-mesh step with ordinary `cellDisplacementx/y` solves,
  no FPE, and finite output;
- a `y=0.01 m` prescribed-motion step with written `pointDisplacement`, moved
  mesh points, and pressure/viscous force decomposition;
- a legacy/new load-only A/B. `U`, `p`, moved `polyMesh/points`, and
  `forces.dat` are byte-identical at 0.005 s; and
- type registration and function-object construction of the new library. The
  deliberately empty-module configuration reaches the adapter banner and
  `preciceDict` read, then fails as the expected negative control before any
  preCICE participant initialization or advance.

This is an ABI/load and OpenFOAM-only regression. It is not a claim that the
new library has the same coupled runtime semantics as the legacy binary.

## Checkpoint semantics audit

Source inspection confirms generic checkpoint registration/restoration for
volume, surface and point scalar/vector/tensor fields. This covers the
available `U`, `p`, `phi`, `Uf`, `meshPhi`, `pointDisplacement`, and
`cellDisplacement` objects when registered. The code stores/restores mesh
points and old mesh points, uses `Time::setTime(value, timeIndex)`, and restores
`oldTime()` and `oldTime().oldTime()` for the registered field families.

`V0`/`V00` are guarded for Foundation 10, but their subcycling path is
deliberately disabled by default in `storeMeshPoints()` and `reloadMeshPoints()`.
The upstream source itself warns that FSI subcycling is not fully supported.
Consequently, the source-level audit is not a runtime rollback qualification:
`CHECKPOINT_SEMANTICS_AUDIT=NOT_COMPLETED` and rollback fingerprints remain
disabled.

## Required next task

Before a new one-window implicit qualification, run a dedicated new-baseline
rollback-state test that exercises a real checkpoint/read-checkpoint cycle and
fingerprints `U`, `p`, `phi`, `Uf`, `meshPhi`, both displacement fields, mesh
points/oldPoints, time/timeIndex, and relevant old-time layers. It must also
declare whether subcycling is forbidden or implement and test a Foundation 10
volume-history policy. Only if that test passes is the next one-window
implicit run authorized.
