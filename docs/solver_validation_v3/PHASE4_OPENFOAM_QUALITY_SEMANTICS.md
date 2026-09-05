# Phase 4 — OpenFOAM observability is not numerical convergence

`run_openfoam_with_metrics_v2.py` uses `OpenFOAMQualityParser`. Source review
establishes the retained field meanings:

- `courant_max`: the maximum from the OpenFOAM `Courant Number` line attached
  to the following `Time` record;
- `residual_max`: the maximum **final** residual among parsed `Solving for`
  lines at that time, not an initial residual and not a named-equation record;
- `continuity_global`: the last parsed global continuity error at that time,
  not a maximum over all continuity lines; and
- `iterations_max`: the maximum parsed solver iteration count at that time.

Therefore record count and field presence only prove
`OBSERVABILITY_COMPLETENESS`. Numerical pass/fail requires a new, frozen
before-run contract with the exact residual and continuity definitions plus
Courant, residual, continuity, and iteration limits. The historical Stage381
and Stage382 records have no such retained contract, so their
`NUMERICAL_QUALITY` status is deliberately `not_evaluable` even when the
observability stream is complete.

Reproduce:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python tools/solver_validation_v3/audit_openfoam_quality_v3.py
python -m unittest tests/solver_validation_v3/test_openfoam_quality_semantics.py
```
