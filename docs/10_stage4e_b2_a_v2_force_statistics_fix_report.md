# Stage 4E-B2-A-v2: force, span and statistics correction

This report covers the independent v2 fixed-cylinder target-Re pilot. It does not claim nine-slice CFD, ANCF coupling, experiment validation, three-dimensional flow, free VIV or lock-in.

## Frozen normalization

The generated two-dimensional mesh has `z/D = [-0.5, 0.5]` and therefore the measured extrusion thickness is `b_mesh = 0.02841 m`. The unit-span concept length is `1 m` and is not the mesh thickness. The corrected contract is:

```text
f_2D = F_OF / b_mesh
Aref_OF = D*b_mesh = 0.0008071281 m^2
Cd = Fx_global/(0.5*rho*|U|^2*D*b_mesh)
Cl = Fy_global/(0.5*rho*|U|^2*D*b_mesh)
```

The six fresh prechecks measured `b_mesh` from the blockMesh bounding box and verified `Aref_control = D*b_mesh`; no `slice_length_m` was applied. The largest raw-force/forceCoeffs absolute coefficient difference was `2.1827872842550278e-11`, below the `1e-10` gate.

## v1 offline diagnosis

The v1 raw files remain untouched and are recalculated only as `diagnostic_only`. The corrected high-laminar-medium mean Cd is `0.876282374554705`, the high-SST-medium mean Cd is `0.8445321966751048`, and the high-SST-fine mean Cd is `0.8119286097808062`. The corrected values do not restore v1 Gate eligibility because the original Aref, RMS and frequency claims were invalid.

`Cd_total_RMS` and `Cd_fluctuation_RMS` are now separate fields; the same separation is used for Cl. A low-amplitude or fewer-than-15-cycle signal returns a null frequency and `frequency_status` indicating non-evaluability.

Evidence JSON is under `results/10_stage4e_target_re_pilot_v2/<run_id>/`.
