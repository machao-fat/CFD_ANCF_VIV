# FORMAL_THREE_SLICE_OWNED_MESH_HISTORY_TWO_WINDOW_V1

## Decision

\`FORMAL_IMPLICIT_TWO_WINDOW = FAIL\` for the one authorized controlled run. CFD and Structure completed two physical commits, but the frozen exact field-history contract did not close at the first restore. The immutable runtime is not reclassified and no rerun was started.

**First blocker:** \`U_UF_OLDTIME_LIFECYCLE_IDENTITY_FAILURE\`.

Generation 1 was checkpointed at physical/OF time \`0.100\`, \`timeIndex=0\`. All three slices restore the current \`U\` and \`Uf\` values exactly, but their recorded \`old_time_levels\` change from \`0\` to \`1\`. The diagnostic deliberately did not access old-time values, so their equality is not claimed. This is a real unresolved identity mismatch under the frozen field-history contract.

## Authorized production candidate and preflight

The run used the owner-observability candidate, not historical build006 or rejected build007.
It carries the frozen pointVectorField-reset production semantics of adapter
`5f7c75d6fc650dd425e8b0edca3e0ba9a69b320546b667b5024246495b433a2d`,
plus diagnostic-only owner observations; it does not add a restore action.

| component | identity |
| --- | --- |
| adapter | \`/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/adapter_owner_diagnostic_build_001/lib/libpreciceAdapterFunctionObject.so\` |
| adapter SHA256 | \`c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17\` |
| worker SHA256 | \`cb0e63116ede3c17d79e256eb1833edcdff8574d178ac1bfc81d2bcc2fad0d06\` |
| OF10 root | \`/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001\` |
| libOpenFOAM SHA256 | \`a34df8ad17f8250071c697d150e593563f2152c194b87fdb906b7a6493f37cde\` |
| libfiniteVolume SHA256 | \`5a820734c0a61a8bd6cdb730d95a651e002848d9d9d4d8a4897ea42608a2e48e\` |
| libfvMotionSolvers SHA256 | \`debc2c86635805c616874612c9c361477424ec58cba77ccc46853b786750eb30\` |
| libfvMeshMovers SHA256 | \`da199da31b42a7b5e07248864cb91c6556dba0afa4db74507879f4124d307e78\` |
| pimpleFoam SHA256 | \`c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43\` |

The persisted preflight passed socket canonicalization, isolated ABI closure, all three moving-mesh case contracts, initial-data/projection, and the existing worker/IPC contracts. Its complete resolved paths and \`ldd -r\` output are in the runtime; no \`/opt/openfoam10\` library entered the closure.

The launcher changed only to accept an explicitly authorized candidate adapter/OF10 prefix and to fail closed on ABI closure. Its historic build006 default remains unchanged.

## Controlled run

| item | result |
| --- | --- |
| runtime | \`runtime/formal_three_slice_owned_mesh_history_two_window_v1_run_001\` |
| scheme | \`parallel-implicit\`, min/max \`2/8\`, no acceleration |
| physical interval | OF \`0.100 -> 0.110 s\`, two windows, \`dt=0.005 s\` |
| processes / worker | all return codes \`0\`; worker closed cleanly |
| commits | window 1 and 2 once each; Structure \`committed_steps=2\` |
| iterations | window 1: 2; window 2: 3; total: 5 |
| wire identity | monotonic and non-restorable; correction sequences \`2,4,6,8,10\` |
| Structure rollback | PASS |
| Force / GF V2 / Newton | PASS / PASS / PASS |
| Quality V4 / FPE | PASS / no FPE |

No ANCF, force mapping, mesh, \`dt\`, PIMPLE, physical parameter, tolerance or checkpoint transaction semantic changed.

## Rollback evidence

The old formal correlation code expects \`states.old_points\`. The owner-observability trace records that private state under \`states.owner_mesh_history.old_points\`; it therefore emits the separate legacy error \`trace state old_points is absent\` for each restore pair. That schema integration defect remains immutable evidence and is not treated as a successful legacy audit.

A new read-only supplemental audit compares each restore with its latest preceding checkpoint, including the owner-managed private snapshot.

| generation | physical time / timeIndex | restores | result |
| --- | --- | --- | --- |
| 1 | \`0.100 / 0\` | one | FAIL: \`U.old_time_levels\`, \`Uf.old_time_levels\` are \`0 -> 1\` in all slices |
| 2 | \`0.105 / 1\` | two | PASS: recorded current fields and owner-managed state identical |

For generation 2, both restores match oldPoints (present, 16524 points, hash \`ed1aa23b4b22b94a\`), V0 (present, 16244 cells, hash \`e310bfc1a7dc104f\`), meshPhi (present, 24226 faces, hash \`f4f527555e12d051\`), motion/time indices, points, \`U/p/phi/Uf\`, and displacement fields. V00 and oldCellCentres are absent at checkpoint and restore. Generation 1 owner state also matches; the new \`U/Uf\` old-time layer is the blocker.

Supplemental evidence: \`results/formal_three_slice_owned_mesh_history_two_window_v1_run_001/owner_mesh_history_supplemental_read_only_audit.json\`. It does not replace the frozen formal auditor.

## Final committed force and response

| slice | raw total Fx / Fy (N per unit span) | integrated streamwise / crossflow (N) |
| --- | ---: | ---: |
| 0 | \`-989.660268 / 85.172571\` | \`-16494.337805 / 1419.542843\` |
| 1 | \`-956.760607 / 83.782635\` | \`-15946.010112 / 1396.377247\` |
| 2 | \`-989.185931 / 85.154530\` | \`-16486.432187 / 1419.242175\` |

Maximum absolute response over accepted and tentative records:

| slice | max \|ux\| (m) | max \|uy\| (m) | max \|vx\| (m/s) | max \|vy\| (m/s) |
| --- | ---: | ---: | ---: | ---: |
| 0 | \`7.358894e-05\` | \`2.709953e-06\` | \`1.612227e-02\` | \`5.937114e-04\` |
| 1 | \`7.195839e-05\` | \`2.649907e-06\` | \`1.630004e-02\` | \`6.002579e-04\` |
| 2 | \`7.357371e-05\` | \`2.709392e-06\` | \`1.611521e-02\` | \`5.934514e-04\` |

These are short-horizon numerical records only, not VIV validation.

## Numerical and mesh quality

Quality V4 passed all slices. Maximum Co was \`0.350303474526\`; terminal primary fluid solves passed. Mesh-motion auxiliary solves at \`0.110 s\` issued efficiency warnings (310 x and 233 y iterations), but their terminal residuals were below \`1e-8\` and Quality V4 did not classify a hard failure.

Read-only standard \`checkMesh -time 0.11\` passed:

| slice | min volume | max non-orthogonality | max skewness | result |
| --- | ---: | ---: | ---: | --- |
| 0 | \`0.00159114029992\` | \`30.6437362191\` | \`0.503085131916\` | Mesh OK |
| 1 | \`0.00159113958030\` | \`30.6437359450\` | \`0.503085132277\` | Mesh OK |
| 2 | \`0.00159114029321\` | \`30.6437362163\` | \`0.503085131938\` | Mesh OK |

## Immutable evidence and next decision

Historical evidence and gates were not overwritten. The new runtime separately retains raw traces, preflight, \`ldd -r\`, worker summary and checkMesh logs. No repair, rerun, 0.05 s run or other coupling run follows from this report.

The minimum next review is to explain why first restore creates \`U/Uf\` old-time layers and to determine whether that can meet the frozen exact-history contract. It requires separate authorization.

\`NEXT_FORMAL_TWO_WINDOW = NOT_AUTHORIZED_PENDING_U_UF_OLDTIME_LIFECYCLE_REVIEW\`
\`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED\`
