# GENERALIZED_FORCE_MISMATCH_ROOT_CAUSE_AUDIT_V1 report

## Decision

`GENERALIZED_FORCE_MISMATCH_ROOT_CAUSE_AUDIT_V1 = NOT_COMPLETED`.

No CFD, preCICE, WSL, or new smoke was started.  The immutable failed runtime was read only.  The generalized-force implementation itself is **not** modified: the step-10 correction input and output necessary to determine its direct numerical cause were not retained before the fail-closed exception.

## Failure identity

| Item | Value |
| --- | --- |
| run id | `moving_mesh_patch_consistency_1s_retry_v1_run_001` |
| case id | `moving_mesh_patch_consistency_1s_retry_v1_case_001` |
| observed failing correction | global/case-local step 10 |
| correction time / tick | 0.050 s / 50,000,000 ns |
| correction transport sequence | 20 |
| prior committed windows | 9 |
| C++ worker process | return code 0; structural adapter raised the mapping gate |

The three slices are unchanged: `(slice_id, s_ref_m, unit_span_m, tributary_length_m)` equals `(0, 8.333333333333334, 1, 16.666666666666668)`, `(1, 25, 1, 16.66666666666666)`, and `(2, 41.666666666666664, 1, 16.66666666666667)`.

## What the immutable runtime contains—and does not contain

For corrections 1–9, the committed record contains the integrated slice forces, Python formal mapping result, C++ total generalized force, C++-derived CFD-only generalized force, predicted state, corrected state, response hash, and identity fields.  The C++ correction input is the committed state before correction; the motion/formal audit uses the target-time prediction, while `H` itself depends only on fixed reference `s_ref_m` and the 50 m / 16-element reference mesh.

For correction 10, the worker response existed long enough for the adapter to check it, but the exception was thrown before the record write.  Thus the runtime contains neither the received three slice-force vectors nor `Q_cpp`, `Q_formal`, the request payload, or a step-10 delta vector.  This makes exact deterministic step-10 replay impossible without altering the historical runtime or running CFD again, both prohibited here.

## Offline replay evidence

A native, diagnostic-only C++ build was produced from the same `ancf_kernel.cpp`; it calls `mapping_H3()` and `external_force()` directly.  It neither advances the ANCF state nor starts any external participant.  The replay fixture uses the saved state and integrated slice forces for each committed correction.

All nine saved corrections replayed.  Python and C++ agree on 0-based reference elements and local coordinates:

| Slice | Element | xi |
| --- | ---: | ---: |
| 0 | 2 | 0.6666666666666667 |
| 1 | 8 | 0 |
| 2 | 13 | 0.3333333333333330 |

The emitted C++ `H` and Python `H` agree at the recorded precision.  Zero force; single-slice x/y/z force; equal, different, and mixed-sign three-slice forces; realistic step-9 force; and its 0.1x / 10x scales all preserve force ordering, integrated-N semantics, per-slice contribution identity, and no hidden tributary-length factor.  No force-ordering, double-scaling, missing-scaling, element-location, H-shape, or local/global-coordinate defect was found in the replayable evidence.

## Historical error evolution and conditioning

The historical gate compared the formal CFD-only `Q_formal` with `Q_cpp_total - base_load`.  Its largest preserved discrepancy is at step 8, DOF 12:

| Quantity | Value |
| --- | ---: |
| max absolute delta, steps 1–9 | `7.450580596923828e-09 N` |
| L2 delta at that step | `1.05371241119304e-08 N` |
| mapping scale | `2.894858578867892e+07 N` |
| normalized infinity delta | `2.5737286965629824e-16` |
| maximum normalized delta over steps 1–9 | `3.691876147882848e-16` |

These are one-to-two-ULP cross-language arithmetic differences, and the fixed `1e-8 N` absolute gate is therefore conditioning-sensitive at the observed generalized-force scale.  This is direct evidence that a **future versioned generalized-force metric** must retain the absolute diagnostic but use a declared scale-normalized hard metric.  It is not proof that the unrecorded step-10 event was only conditioning: the step-10 vector is absent.  The historical failure remains `FAIL` and no tolerance was changed.

## Evidence-persistence repair

The authoritative structure participant now persists every correction attempt before the generalized-force gate, including identity, committed input state, prediction state, all integrated slice forces, slice metadata, `H`, `Q_formal`, C++ total/CFD generalized forces, formal-input hash, C++ response hash, and exact binary request hash.  The C++ adapter emits the exact request payload SHA-256 for real wire requests.  These are diagnostics only; neither ANCF equations nor force assembly changed.

## Root-cause classification and next decision

The direct primary root-cause class is `OTHER: correction-attempt evidence persistence bug`.  `GENERALIZED_FORCE_METRIC_CONDITIONING` is supported for a future versioned contract, but it is deliberately not used as a retroactive root-cause classification for step 10.

The log-only `Courant max ≈ 7.10` at the aborted run remains `SECONDARY_NUMERICAL_RISK`; it is unrelated to the generalized-force audit and no CFD numerical setting was changed.

`NEXT_CORRECTED_SMOKE = NOT_AUTHORIZED`.

After an explicit future authorization and a pre-frozen V2 generalized-force metric/evidence contract, the appropriate diagnostic duration is **0.1 s**: it covers the prior 0.05 s failure while minimizing exposure to the independent Courant risk.  This task did not run it.

## Evidence

- Machine replay summary: `results/generalized_force_mismatch_root_cause_audit_v1/generalized_force_replay_v1_summary.json`
- Machine gate: `results/generalized_force_mismatch_root_cause_audit_v1/audit_gate.json`
- Replay tool: `tools/generalized_force_mismatch_root_cause_audit_v1/replay.py`
