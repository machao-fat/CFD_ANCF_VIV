# OpenFOAM implicit rollback observability and one-window requalification V2

## Status

`ONE_WINDOW_IMPLICIT_REQUALIFICATION_V2 = FAIL` (fail closed; no V2 CFD window was started).

## Adapter audit

The deployed binary is `/home/machao/OpenFOAM/stage315_adapter_build/libpreciceAdapterFunctionObject.so` with SHA-256 `26ad8529822f96ca8ddfb3370f85257b0d19b56958538d6073cf8af897aac572`. Its actual prior-runtime banner is v1.3.0. It exports the checkpoint methods required for field, mesh, and time restoration. The source-level mechanism is: all registered geometric fields are copied/restored by type; existing old-time levels are copied/restored; `mesh_.points()` and `mesh_.oldPoints()` are retained; `mesh_.phi()` is handled through the mesh checkpoint; and `Time::setTime(value, index)` restores time and `timeIndex`.

The only recoverable candidate source is revision `3d45c38c5091331906bd32517b400d8cb0786bb1`, whose banner is v1.3.0. It does not provenance-match the deployed v1.3.0 binary. A build against the installed OpenFOAM 10 environment failed before linking, due to incompatible/missing headers: `faceTriangulation.H`. Therefore an instrumented replacement library would not be an auditable build of the deployed adapter.

## Required observability disposition

No diagnostic callback library was installed or loaded. Consequently `U`, `p`, `phi`, `pointDisplacement`, `cellDisplacement`, mesh points, `time`, and `timeIndex` remain `NOT_OBSERVABLE` at the actual callback boundaries. `Uf` and `meshPhi` are semantically checkpointed when registered / through the mesh checkpoint respectively, but their direct runtime identities also remain `NOT_OBSERVABLE`. No claim of rollback identity is made.

## Decision

The first blocker is `DEPLOYED_ADAPTER_SOURCE_AND_BUILD_ENVIRONMENT_NOT_REPRODUCIBLE`. The minimal repair is to recover the exact source revision and the OpenFOAM 10 build environment that produced deployed library SHA-256 `26ad8529822f96ca8ddfb3370f85257b0d19b56958538d6073cf8af897aac572`, then rebuild a distinct diagnostic-only adapter with callback snapshots disabled by default. Only after its non-intrusiveness regression passes may a fresh one-window implicit requalification run.

`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`
