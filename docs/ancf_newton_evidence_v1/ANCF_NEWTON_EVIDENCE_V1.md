# ANCF Newton evidence V1

## Purpose

This versioned writer preserves Newton diagnostics already returned by the C++
worker for every future prediction and correction.  It does not alter any
historical runtime, including run_008.

## Wire evidence and semantics

The current worker response carries `iterations`, `residual`, `return_code`,
and `finite_value_audit`.  It does not carry an initial Newton residual or an
explicit `converged` bit.  Therefore V1 persists only the real wire fields:
`newton_iterations`, `newton_final_residual`, `worker_return_code`, and the
finite-state audit.  `newton_converged=true` is explicitly recorded as a
derived fact: the C++ kernel throws when its Newton procedure does not
converge, and the response was accepted only with `return_code=0`.

No initial residual is fabricated.

## Per-record identity

Each `ancf-newton-evidence-v1` record contains run/case identity, global step,
time, nanosecond integer tick, prediction/correction phase, transport sequence,
correction sequence where applicable, the frozen maximum Newton iteration
count, diagnostics, and `q`, `qdot`, and `qddot`.  A SHA-256 of those three
state vectors links a response diagnostic to the exact ANCF state it produced.

The writer rejects absent diagnostics, non-finite values, non-zero return
codes, sequence/tick mismatches, excess iterations, duplicate identities,
missing prediction/correction pairs, and state-hash mismatches.  A completed
200-window smoke therefore requires exactly 400 independently auditable Newton
records.

## Scope

The implementation is installed in the future three-slice participant path.
It is not a re-analysis of run_008; run_008 remains read-only and its Newton
execution status remains historically not evaluable.
