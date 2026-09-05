# H/H^T moment-balance root-cause audit V1

Status: `MOMENT_MAPPING_STATUS=METRIC_DEFINITION_REQUIRES_VERSIONING`.

The legacy error is not a full physical-moment contract: it is the relative
z-moment difference divided by the magnitude of that same net moment.  At
the historical maximum (`global_step=56433`, `t=282.165 s`), the retained
fluid net moment is `4.0293789659e-9 N m`, whereas the sum of absolute
individual force-moment contributions is `6.736725399e-2 N m`.  The resulting
cancellation condition number is `1.6719e7`; a roughly `1.8e-18 N m`
floating-point-order difference appears as the retained `4.442427e-10`
relative value.  Historical logs do not retain the mapped absolute moment,
so that difference cannot be re-derived independently; the old value remains
authoritative and remains a fail.

This is not a mapping-mathematics bug, reference-point inconsistency, or
cross-product-sign error.  Analytical tests pass force, full-vector moment,
and virtual-work identities for a nonzero off-axis force, zero-resultant
pure couple, non-symmetric three-slice load, translated origin, near-zero
moment, and large cancellation.  The normal non-pathological cases have
force/moment/virtual-work normalized errors below `1e-10`.

For `Q=sum(H_i^T F_i)`, `Q^T delta_q=sum(F_i^T H_i delta_q)` holds directly.
Choosing `delta_q` as a rigid translation recovers resultant force; choosing
it as a rigid rotation about an explicit origin recovers `sum((r_i-origin)
x F_i)`.  This includes ANCF slope DOFs, so merely summing translational DOF
entries is not the defining proof of moment conservation.

No production mapping code was changed.  Future contracts should report
both absolute moment mismatch and the versioned contribution-scale-normalized
metric in `src/coupling/moment_mapping_audit_v1`; legacy Stage385 must not be
retroactively passed.
