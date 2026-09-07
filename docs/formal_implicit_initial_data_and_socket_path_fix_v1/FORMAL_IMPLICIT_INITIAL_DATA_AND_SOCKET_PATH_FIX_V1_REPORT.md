# FORMAL_IMPLICIT_INITIAL_DATA_AND_SOCKET_PATH_FIX_V1

## Scope and immutable runtime

The only authorized physical-window attempt is immutable at
`runtime/formal_implicit_initial_data_and_socket_path_fix_v1_run_006`.
It stopped during Structure's pre-`initialize()` initial-data validation.
No preCICE participant completed initialization, no checkpoint/trial/rollback
occurred, and no CFD physical timestep was solved or committed. No 0.05 s or
longer coupled run was started.

Earlier `_001`--`_005` directories are preserved launcher/pre-execution
artifacts; none reached a CFD physical solve. They are not used as positive
qualification evidence.

## Initial-data repair and regression

The production Structure participant now obtains registered
`Structure-Mesh` IDs before `initialize()`, calculates its initial motion from
the frozen ANCF state, validates the 40-by-2 finite payload in registered
vertex order, calls `requires_initial_data()`, and writes `Displacement`
before `initialize()` when required. It records the state and payload hashes.

The real preCICE 3.4.1 no-CFD regression passed at
`results/formal_implicit_initial_data_and_socket_path_fix_v1_regression_004/initial_data_and_path_regression.json`:

- zero initial Displacement: PASS;
- known nonzero `+0.002 m` initial Displacement: PASS and received unchanged;
- an intentionally omitted required payload: project fail-closed before
  `initialize()`;
- initialization data are two-dimensional meters in registered mesh order.

The formal attempt found a new, direct production-contract error in the added
zero-geometry guard. Its frozen no-flow state maps to zero exchanged x/y
components for all slices, but to the following unexchanged axial z values:

| slice | ux [m] | uy [m] | uz [m] |
|---:|---:|---:|---:|
| 0 | 0 | 0 | 0.0132332091028786 |
| 1 | 0 | 0 | 0.0529515616443881 |
| 2 | 0 | 0 | 0.110292698472797 |

`Structure-Mesh` is a 2D interface and its initial Displacement payload is
x/y only. The guard incorrectly required z to be zero too, then raised
`NO_FLOW_EQUILIBRIUM does not map to zero initial interface displacement`.
This is the unique first blocker. It is not hydrodynamic evidence.

## Socket-path repair and regression

The authoritative WSL conversion helper is
`src/coupling/precice_path_v1.py`, used by the shared three-slice generator
and the formal launcher. It classifies Windows-drive, WSL-mounted, Linux
absolute, and relative paths once; it no longer prefixes an already-Linux path
with `/mnt/`. Target-directory availability is checked in the target WSL
namespace, not as a Windows `\\mnt` path.

The same regression passed:

- `D:\\work\\socket` -> `/mnt/d/work/socket`;
- `/mnt/d/work/socket` unchanged;
- `/home/machao/socket` unchanged;
- empty paths, missing parents, and an unwritable `/proc` parent fail closed.

All three Fluid participants in `_006` started through normal OpenFOAM and
preCICE configuration and reached socket communication setup; no malformed
`/mnt//nt/...` path or socket-permission error occurred.

## Production preflight

- initial-data API regression: PASS;
- socket canonicalization regression and target-directory preflight: PASS;
- three-slice moving-mesh case preflight: PASS before launch;
- frozen precursor and U/p/phi transfer manifest: PASS before launch;
- checkpoint-aware Structure regression, monotonic wire identity, time-layer
  contract, and realtime-containment regression: inherited frozen PASS;
- actual Fluid adapter (all three):
  `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib/libpreciceAdapterFunctionObject.so`;
  SHA256 `6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`;
  upstream `d53753b1c927b2413b02299c9da15725b3e772f0`;
  patches `0001, 0002, 0004, 0005`.

## One-window result

`FORMAL_IMPLICIT_INITIAL_DATA_AND_SOCKET_PATH_FIX_V1 = FAIL`.

- one physical window: not initialized; 0 commits;
- coupling iterations: 0;
- Structure rollback: not evaluable;
- Fluid field/history and dynamic-mesh rollback: not evaluable;
- final raw Fx/Fy and integrated structural forces: not available;
- Quality V4, Generalized Force Metric V2, and ANCF Newton: not evaluable;
- no FPE, negative-cell, force, or numerical conclusion is available.

The next minimal task is a dimension-aware Structure initial-interface
contract: validate and zero-check only the actual 2D transmitted x/y data,
while separately recording z as untransmitted state. It must add a regression
covering nonzero unexchanged z, then request a fresh one-window authorization.

`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.
