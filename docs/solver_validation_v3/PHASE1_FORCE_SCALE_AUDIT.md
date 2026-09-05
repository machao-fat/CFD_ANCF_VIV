# Phase 1 — force-scale audit

The Stage382 participant at `tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py` reads the preCICE `Force` field at every interface vertex, sums those vectors with `force_sum()`, and forwards the three sums to the C++ worker as `slice_force`.

The retained Stage382 diagnostics do not contain `unit_span_m`, a tributary/slice length, a force representation, the raw OpenFOAM integral, a two-dimensional force density, or an integrated structural slice force.  Consequently its physical force scale is **not evaluable**.  Conservation of those summed values under `H^T` is only a mapping identity; it does not validate the units entering the mapping.

For a future run, the existing Draft 0.2.1 `multi_slice_mapping` contract is the required interface:

`F_slice [N] = F_OpenFOAM [N] / unit_span_m * slice_length_m`.

It rejects absent/non-positive span and slice-length fields, records all three force levels, and maps only the integrated force.  The new V3 test uses this contract and verifies force/moment/virtual-work identities below `1e-10`.

The audit result is `results/solver_validation_v3/phase1_force_scale_audit.json`.  It is read-only with respect to Stage341–Stage385.
