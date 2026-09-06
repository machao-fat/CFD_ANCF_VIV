# PARALLEL_EXPLICIT_FSI_TIMESTEP_STABILITY_DIAGNOSTIC_V1_REPORT

- Run: `parallel_explicit_fsi_timestep_stability_v1_run_001`
- Frozen comparison: baseline `dt=0.005 s`, diagnostic `dt=0.0025 s`; all other authorized model, precursor, state, mesh, and coupling identities were retained.
- OpenFOAM time identity: `t_OF=0.100 s+tau`.
- Status: `FAIL`. The run committed 27/40 windows, then reached the frozen containment envelope and OpenFOAM FPE before `tau=0.100 s`.

## V4 and precursor preflight

- `OPENFOAM_QUALITY_V4_CONTRACT`: frozen before the run. Auxiliary `cellDisplacement*` convergence is a validity condition; more than 200 iterations is an efficiency warning only.
- `dt=0.0025 s` zero-motion precursor-continuation preflight: `PASS`; first advanced raw Fx was `1195.784385636 N`, with persisted-state hashes matched, `Uf` reconstructed, and zero `meshPhi`.

## Coupled result

- Committed windows: `27/40`.
- max |raw Fx| [N per 1 m] slice 0/1/2: `[77501708.2473057, 24538198.73990175, 77642114.2857108]`.
- max |vx| [m/s] slice 0/1/2: `[623.085041465518, 64.27287889165422, 623.3234096543589]`.
- max |ux| [m] slice 0/1/2: `[1.4544249691284485, 0.09973428254413186, 2.4338489484821593]`.
- max fluid Courant slice 0/1/2: `[16402.1120109, 8.28984455044, 24.2387542772]`.
- First containment crossings: raw Fx `tau=0.035 s`; |vx| `tau=0.0525 s`; |ux| `tau=0.0575 s`.
- First raw coupled force at `t_OF=0.1025 s` (all slices): pressure `481.9867420724 N`, viscous `713.7976435636 N`, total `1195.784385636 N`; it is startup-balanced, not the historical cold-start impulse.

## Common-time timestep comparison

- R_F (slice 0/1/2): `[79.4802705524172, 46.353004537356, 79.24153382083723]`.
- R_v (slice 0/1/2): `[54.30687814926528, 11.261638925296534, 54.029259234345126]`.
- R_u (slice 0/1/2): `[39.52670499943858, 7.509443319329299, 65.83382802472246]`.
- R_Co (slice 0/1/2): `[10083.562090300771, 10.256322713514384, 14.843517874830544]`.
- 5x/10x/100x precursor-drag and |vx|>1 m/s crossing times are in `results/.../dt_half_analysis.json`. For slices 0/2 these changed from baseline `0.040/0.050/0.080/0.075 s` to `0.0175/0.0225/0.035/0.0375 s`; slice 1 changed to `0.0175/0.0225/0.040/0.0425 s`.
- Algorithmic midpoint streamwise work [J], dt-half: `[287396241.00617504, 8759109.66287527, 4069800364.2667217]`; baseline: `[-144555.44425817975, 52058.52908242351, -146068.16637322455]`. The failed partial dt-half data are not physical power evidence.
- Fx sign reversals, dt-half/baseline: `[13, 14, 13]` / `[11, 10, 11]`.
- Classification: `WORSE_AT_SMALLER_DT`. This does not support a simple claim that reducing the explicit one-window time layer stabilizes the closed loop.

## Quality and mesh

- V4 evaluation: slice status `['fail', 'fail', 'fail']`. It failed on fluid Courant/continuity and incomplete primary pressure terminal evidence after FPE; this is distinct from auxiliary PCG work.
- mesh auxiliary max iterations/final residual: `{'0': {'max_iterations': 325, 'max_final_residual': 9.91915950551e-09, 'status': 'warning'}, '1': {'max_iterations': 311, 'max_final_residual': 9.96613380692e-09, 'status': 'warning'}, '2': {'max_iterations': 311, 'max_final_residual': 9.97481375297e-09, 'status': 'warning'}}`. Final residuals remained below `1e-8`; V4 labels the high PCG counts as efficiency warnings, not the primary validity failure.
- Full post-run checkMesh sweep: `{'0': {'first_failed_mesh_time_s': 0.165, 'negative_volume_count': 45, 'minimum_negative_volume': -0.0262181884261, 'sweep_return_mesh_ok_until_failure': False}, '1': {'first_failed_mesh_time_s': None, 'negative_volume_count': None, 'minimum_negative_volume': None, 'sweep_return_mesh_ok_until_failure': True}, '2': {'first_failed_mesh_time_s': None, 'negative_volume_count': None, 'minimum_negative_volume': None, 'sweep_return_mesh_ok_until_failure': True}}`. Slice 0 first showed 45 negative-volume cells at `t_OF=0.165 s`; slices 1 and 2 remained Mesh OK through their last written times. This is downstream of the escalation, not evidence of an initial mesh defect.
- Generalized-force V2, force conversion, and ANCF core were not reopened by this task; the run did not complete enough windows to qualify them as an all-run pass.

## Decision

- `EXPLICIT_TIME_LAYER_STABILITY`: not supported by this single dt-half test; smaller dt made the observed runaway earlier and larger.
- `ADDED_MASS_INSTABILITY`: `NOT_ESTABLISHED`; this test only rejects simple timestep stabilization, it does not identify a mechanism.
- Recommended next single control (not run here): a parallel-implicit versus parallel-explicit comparison at the original `dt=0.005 s`, with identical precursor and state. Do not combine it with another dt, relaxation, mesh, or physical-model change.
- No VIV, lock-in, Strouhal, amplitude, or frequency conclusion is made.
