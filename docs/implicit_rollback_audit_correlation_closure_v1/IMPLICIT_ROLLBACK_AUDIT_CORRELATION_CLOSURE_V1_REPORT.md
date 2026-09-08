# IMPLICIT_ROLLBACK_AUDIT_CORRELATION_CLOSURE_V1_REPORT

## Scope

This task changed only the formal rollback auditor and its no-CFD regressions. It did not change OpenFOAM, the preCICE adapter, ANCF, IPC production protocol, checkpoint implementation, timestep, mesh, solver settings, force scaling, mapping, or fixed-point contract. The prior formal two-window runtime remains immutable.

## A — audit root cause and minimal correction

The former auditor built `{window_id: checkpoint}`. `window_id` is an adapter diagnostic counter rather than a unique physical checkpoint identity. In the immutable two-window trace, the next physical checkpoint was emitted at physical time `0.105 s`, timeIndex 1 but still had adapter `window_id=1`; it overwrote the `0.100 s` checkpoint. Its restores had adapter `window_id=2`, so the former auditor both mismatched the first restore and could not locate the second generation.

The replacement creates a distinct generation for every `CHECKPOINT_WRITE` in canonical append-only trace order. Each restore binds only to the latest chronologically preceding generation, then must match its physical time, timeIndex, adapter build SHA, current fields, mesh points, old points, relevant old-time semantics, and meshPhi lifecycle semantics. The versioned contract is `tools/implicit_rollback_audit_correlation_closure_v1/rollback_generation_correlation_contract_v1.json`.

## B — audit regression

`ROLLBACK_AUDIT_CORRELATION_REGRESSION = PASS`.

- Accepted: one checkpoint/restore; repeated adapter `window_id`; same checkpoint restored multiple times; a new checkpoint generation replacing the prior active generation.
- Rejected fail-closed: missing checkpoint; restore preceding checkpoint; timeIndex mismatch; ambiguous/nonmonotonic event sequence; and a real fingerprint mismatch.

## C — immutable historical re-audit

`HISTORICAL_TWO_WINDOW_CORRECTED_REAUDIT = FAIL`; the original `FORMAL_IMPLICIT_TWO_WINDOW = FAIL` remains unchanged.

For every slice, the lifecycle pairs are:

| Generation | checkpoint event | restore event(s) | physical time / timeIndex | Result |
|---:|---:|---:|---|---|
| 1 | 1 | 3 | 0.100 s / 0 | PASS |
| 2 | 4 | 7 | 0.105 s / 1 | PASS |
| 2 | 4 | 9 | 0.105 s / 1 | FAIL: `old_points` |

For the failed generation-2 second restore, `U`, `p`, `phi`, `Uf`, `pointDisplacement`, `cellDisplacement`, full `mesh_points`, time/timeIndex, and all relevant old-time checks match the checkpoint. `meshPhi` remains an accepted persistent/reconstructed lifecycle state. Only `old_points` differs, consistently on slices 0, 1, and 2. This is a real mesh-history rollback mismatch under the frozen contract, not an auditor pairing artefact.

## D — fresh CFD authorization

Because the corrected read-only re-audit found a real required-state mismatch, Phase D did not pass. Therefore the newly authorized CFD two-window test was **not run**. No runtime was created, modified, or retried for that phase.

The old two-window runtime's already-recorded numerical evidence remains only historical context: 2/2 commits, iterations 2 and 3, `Quality V4`, Newton 4/4, force contract, and Generalized Force V2 PASS; its final raw `(Fx,Fy)` [N per 1 m] for slices 0/1/2 were `(-989.6602683,85.1725706)`, `(-956.7606067,83.7826348)`, and `(-989.1859312,85.1545305)`. It does not close the rollback gate.

## Decision

- `CROSS_WINDOW_IPC_LIFECYCLE = PASS` (unchanged).
- `HISTORICAL_TWO_WINDOW_CORRECTED_REAUDIT = FAIL`.
- `FRESH_FORMAL_IMPLICIT_TWO_WINDOW = NOT_RUN`.
- First blocker: `OLD_POINTS_ROLLBACK_IDENTITY_FAILURE`, checkpoint generation 2, second restore, all three slices.
- `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.

The next task needs a registry-safe, source-level investigation of `oldPoints` checkpoint/restore ownership and lifetime. It must not relax this audit criterion or start a longer coupled run.
