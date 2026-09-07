# OF10_REGISTRY_SAFE_ROLLBACK_AND_NONZERO_MOTION_QUALIFICATION_V1

## Final decision

`ADAPTER_ROLLBACK_QUALIFICATION = FAIL`.

The only fresh no-ANCF runtime is immutable:
`runtime/of10_registry_safe_rollback_nonzero_motion_qualification_v1_run_001`.
It completed exactly one physical window, `0.100 -> 0.105 s`, with three
fixed-point trials and two actual rollbacks. No ANCF-CFD or longer run occurred.

The first blocker is `MOTION_FIXTURE_TIMING`: the planned `-0.002 m` sample
did not enter the third trial.

## State lifecycle and candidate library

Rejected `0003-openfoam10-checkpoint-lifecycle-and-motion-timing.patch` is
kept as a `REJECTED_EXPERIMENT`; `.005` never applies it. Its early
`mesh_.phi()` call was illegal before OF10 creates a mesh flux object.

`of10_rollback_state_equivalence_contract_v1.json` freezes these categories:

- Exact persistent state: U, p, phi, cellDisplacement, mesh points, time/index.
- Legally reconstructed state: meshPhi, oldPoints, and initially lazy U/Uf oldTime.
- Not applicable: V0/V00 and fluid subcycling.

`meshPhi` is now treated as an OF10 `movePoints()`-derived flux. It is not
created at checkpoint, deleted, or replaced. `oldTime` levels are not manually
altered: their validity is tested by the next same-input solve.

| Item | Value |
| --- | --- |
| Upstream | `precice/openfoam-adapter` OF10 `d53753b1c927b2413b02299c9da15725b3e772f0` |
| Patch | `0004-registry-safe-rollback-and-motion-timing.patch` |
| Environment | OF Foundation 10, GCC 11.4, preCICE 3.4.1 |
| Diagnostic library | `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_005/lib/libpreciceAdapterFunctionObject.so` |
| SHA256 | `6a260dfb6c39a83d84864ac2973303416dde1a8d215b5f6eaeaf95e1d8b86f08` |
| Build/link check | PASS; no unresolved `ldd -r` dependency |

The patch reads initial total Displacement after preCICE initialization and
uses OF10 `movePoints()` plus post-trial `mesh_.phi()` access to reconstruct
derived flux at restored time.

## Results

OFF/ON regression from
`runtime/of10_registry_safe_rollback_nonzero_motion_qualification_v1_off_on_001`
PASSed. U, p, phi, full mesh points, and `forces.dat` hashes are identical.

The real trace is:

```
CHECKPOINT_WRITE                 t=0.100 index=0
PRE_ROLLBACK_TRIAL               t=0.105 index=1
POST_ROLLBACK_BEFORE_NEXT_INPUT  t=0.100 index=0
PRE_ROLLBACK_TRIAL               t=0.105 index=1
POST_ROLLBACK_BEFORE_NEXT_INPUT  t=0.100 index=0
FINAL_COMMIT                     t=0.105 index=1
```

Initial `+0.002 m` data moved actual mesh centroid y from
`0.17720998354325726` to `0.1778611381392648`. The normal preCICE-to-adapter
motion path is therefore proven for nonzero input.

After each rollback, mesh points returned exactly to checkpoint. The following
same-input `+A` trial exactly reproduced canonical U, p, phi, Uf,
meshPhi-current value, displacement, mesh points, and oldPoints. U/Uf oldTime
changed from zero to one level, but same-input output remained exact, so no
numerical-state pollution is observed in the non-subcycled path.

## First blocker

The source reads post-advance data with `relativeReadTime=0.0`. This requests
the beginning-of-window sample. The newly written `-A` is an end-window sample,
so the third trial retained `+A` geometry. Different-input isolation is not
established. No third patch or rerun was attempted.

Committed raw force at OF time `0.105 s` is pressure
`(572.1613776045, -61392.62632618) N`, viscous
`(715.1405925084, -699.6662157170) N`, total
`(1287.3019701129, -62092.2925418950) N`.

| Gate | Status |
| --- | --- |
| CHECKPOINT_LIFECYCLE | PASS for same-input registry-safe reconstruction |
| MOTION_FIXTURE_TIMING | FAIL |
| NON_INTRUSIVE_REGRESSION | PASS |
| FIELD_HISTORY_EQUIVALENCE | PASS for persistent state and same-input solve |
| NONZERO_MESH_ROLLBACK | PASS for `+A`, no accumulation |
| DETERMINISTIC_RETRY | PASS for same input |
| DIFFERENT_INPUT_ISOLATION | FAIL / not established |
| TIME_COMMIT_IDENTITY | PASS, one commit |
| ADAPTER_ROLLBACK_QUALIFICATION | FAIL |

`NEXT_FORMAL_ANCF_ONE_WINDOW = NOT_AUTHORIZED`.
