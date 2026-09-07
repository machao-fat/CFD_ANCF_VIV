# REPRODUCIBLE_OPENFOAM10_ADAPTER_ROLLBACK_QUALIFICATION_V1_REPORT

## Decision

ADAPTER_ROLLBACK_QUALIFICATION = FAIL.

The first blocker is PRECICE_NON_SUBCYCLED_EXCHANGE_CONFIGURATION_INVALID.
The real-preCICE runtime reproducible_openfoam10_adapter_rollback_qualification_v1_run_002 is retained. It had no OpenFOAM physical solve, no adapter checkpoint callback, and no rollback.

preCICE 3.4 rejected the fixture before initialization: waveform-degree=0 requires substeps=false on the Force exchange. This is a fixture configuration error, not evidence for or against CFD field, mesh, or time restoration. It was not modified or rerun.

## Frozen non-subcycled policy

The policy is stored in tools/reproducible_openfoam10_adapter_rollback_qualification_v1/non_subcycled_adapter_rollback_policy_v1.json.

- Physical timestep: 0.005 s.
- One OpenFOAM physical step equals one preCICE coupling window.
- PIMPLE outer correctors are not subcycling.
- preCICE fixed-point trials are checkpoint/restore trials, not extra physical steps.
- FLUID_SUBCYCLING = FORBIDDEN.
- Constant-waveform exchanges require explicit substeps=false.

## V0/V00 and volume history audit

The pinned adapter source is d53753b1c927b2413b02299c9da15725b3e772f0.

| State | Source policy | Current non-subcycled path |
| --- | --- | --- |
| U, p, phi | registered fields and existing old-time levels are copied/restored | persistent/restored |
| Uf | copied as a surface vector when registered | runtime observable after a valid callback |
| meshPhi | mesh phi has a dedicated moving-mesh checkpoint | runtime observable after a valid callback |
| pointDisplacement, cellDisplacement | registered point/volume fields and existing old-time levels are copied/restored | persistent/restored |
| mesh points, oldPoints | points and oldPoints retained; restore uses move then movePoints | persistent/restored by source design |
| time, timeIndex | Time::setTime(value,index) | persistent/restored |
| V0, V00 | guarded implementation is deliberately commented as a subcycling-only TODO | NOT_APPLICABLE_NON_SUBCYCLED |

No current non-subcycled step invokes V0/V00. This task did not alter that path.

## Diagnostic library

- Source pin: d53753b1c927b2413b02299c9da15725b3e772f0.
- Base patch: isolated ADAPTER_TARGET_DIR.
- Diagnostic patch: 0002-diagnostic-rollback-fingerprints.patch.
- Library: /home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_002/lib/libpreciceAdapterFunctionObject.so.
- SHA256: 65a7e25619a97832034a5f4ec41c633a069d7ebcf48508be79946469da89ab51.
- ELF build ID: 607c4d1991871aad45e809fa6ee4157929e6c459.

Diagnostics are opt-in through PRECICE_ADAPTER_ROLLBACK_DIAGNOSTICS_PATH. They emit canonical FNV-1a fingerprints at CHECKPOINT_WRITE, PRE_ROLLBACK_TRIAL, POST_ROLLBACK_BEFORE_NEXT_INPUT, and FINAL_COMMIT without changing solver state, checkpoint content, coupling data, or iteration order.

## Gate status

| Gate | Status |
| --- | --- |
| SUBCYCLING_POLICY | PASS |
| VOLUME_HISTORY_POLICY | PASS |
| ROLLBACK_INSTRUMENTATION | PASS |
| NON_INTRUSIVE_REGRESSION | NOT_COMPLETED |
| REAL_CHECKPOINT_CALLBACK | FAIL |
| FIELD_ROLLBACK_IDENTITY | NOT_COMPLETED |
| MESH_ROLLBACK_IDENTITY | NOT_COMPLETED |
| TIME_HISTORY_ROLLBACK | NOT_COMPLETED |
| DETERMINISTIC_RETRY | NOT_COMPLETED |

The intended test used PRECURSOR_STATE_V1, one 0.005 s window, and distinct prescribed transverse trial inputs +0.002 m and -0.002 m. It did not advance a CFD physical step.

## Next decision

NEXT_ONE_WINDOW_IMPLICIT = NOT_AUTHORIZED.

The next task must fix the isolated fixture with substeps=false, run the OFF/ON non-intrusiveness regression, then run one fresh real-preCICE rollback window. It must remain limited to one 0.005 s window and may not connect ANCF.
