# Stage 374: Convergence Observability Repair v1

This stage is offline and read-only. It audits the completed Stage 372 runtime
without starting MATLAB, OpenFOAM, WSL, or CFD and without changing any old
runtime, physical parameter, time step, threshold, protocol, or formal status.

The repair makes three distinctions explicit:

* identity continuity (global step, case-local step, time/tick, and three-slice shape);
* quality observability (every expected OpenFOAM sample must contain finite
  `courant_max`, `residual_max`, `continuity_global`, and `iterations_max`);
* statistical observability (positive interior peaks, 1 s smoothing, 4 s
  minimum spacing, per-slice interface displacement, and aggregate force).

No missing terminal Courant value is interpolated. The existing Stage 372
terminal omission therefore remains a quality-audit failure, while its source
runtime stays protected and unchanged. The robust frequency reanalysis can
pass independently; amplitude stability and formal convergence remain separate
claims.

Run the audit from the project root:

```powershell
python .\tools\stage374_convergence_observability_repair_v1\audit_stage372_v3.py
python -m unittest discover -s .\tests\convergence_observability_v3 -p "test_*.py" -v
python .\tools\stage374_convergence_observability_repair_v1\prepare_short_window_contract.py
```

Gate output:

```text
STAGE4F_D_CONVERGENCE_OBSERVABILITY_REPAIR_V1_GATE: pass
```

This Gate means the repair/audit procedure itself is complete. It does not
promote `FORMAL_STROUHAL_STATUS`, `STABLE_VIV_RESPONSE_CLAIM`, or
`LOCK_IN_CLAIM`; all remain `not_completed` until a future authorized run
records the required aligned observables.

The generated short-window contract is an unauthorised template. It explicitly
requires terminal `courant_max`, aligned scalar response streams, finite values,
and fail-closed handling of missing data, while keeping real process launch
disabled until a separate user authorization.
