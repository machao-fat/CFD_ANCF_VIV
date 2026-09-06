# PRECONDITIONED_COUPLED_0P1S_SMOKE_V1_REPORT

- Run: `preconditioned_coupled_0p1s_smoke_v1_run_003`
- Result: `FAIL`
- Windows: `20/20`
- OpenFOAM time identity: `t_OF = 0.100 s + coupling tau`
- Structural initial state: `NO_FLOW_EQUILIBRIUM`; the mean-drag equilibrium was not used.
- Precursor manifest/state copy: `PASS`; `U`, `p`, and `phi` hashes match `PRECURSOR_STATE_V1`.

## Startup force

slice 0: p=542.616707016 N, visc=705.587217378 N, total=1248.20392439 N, integrated=20803.3987399 N; slice 1: p=542.616707016 N, visc=705.587217378 N, total=1248.20392439 N, integrated=20803.3987399 N; slice 2: p=542.616707016 N, visc=705.587217378 N, total=1248.20392439 N, integrated=20803.3987399 N

## Gates

- launch_return: `PASS`
- committed_20: `PASS`
- precursor_transfer_v2: `PASS`
- cold_start_guard: `PASS`
- first_force_identity: `PASS`
- force_contract: `PASS`
- mapping: `FAIL`
- generalized_force_v2: `PASS`
- moving_mesh_tracking: `PASS`
- mesh_quality_every_step_observability: `FAIL`
- quality_v3: `FAIL`
- newton_40: `PASS`
- structural_startup_guard: `FAIL`
- time_offset_identity: `PASS`
- conditional_force_independence: `PASS`
- no_participant_fpe_disconnect: `PASS`

## Observed maxima

- max |ux| per slice [m]: `[0.036796008398603086, 0.013281181880342038, 0.036969579644801756]`
- max |vx| per slice [m/s]: `[11.473409312038456, 5.707240244337866, 11.536775045365177]`
- min cell volume: `0.00158422951478`
- max non-orthogonality: `30.6412924219`
- max skewness: `0.503087913149`
- fluid Courant max: `1.63295213989`
- mesh-motion Courant proxy max: `0.1387966907196013`
- generalized-force V2 max utilization: `0.03671232204816031`
- raw force files byte-identical: `False`
- structure motions distinct: `True`

## Failure chronology

- At coupling `tau = 0.005 s` / OpenFOAM `t = 0.105 s`, the fresh raw force was 1248.203924 N per slice, well below the frozen 5000 N cold-start guard. The adapter received the same value, and the integrated structural force was 20803.398740 N per slice.
- At `tau = 0.015 s` / OpenFOAM `t = 0.115 s`, the V3 mesh-motion auxiliary solver-health classification first failed because the `cellDisplacementx/y` solves required 310/233 linear iterations. Primary Ux/Uy/p terminal convergence remained passing.
- The maximum fluid Courant values were 1.626619, 0.808267, and 1.632952 for slices 0–2, respectively; each exceeds the frozen V3 Courant limit. The final mesh-motion increment proxy was 0.138797, and the final meshes themselves remained valid at the three independently checked final snapshots.
- At `tau = 0.075 s`, `max |vx| = 1.403524 m/s` first exceeded the frozen 1 m/s startup guard. The final maxima were 11.473409, 5.707240, and 11.536775 m/s.
- At step 19 (`tau = 0.095 s`), the legacy absolute mapped-moment discrepancy was 1.194419e-7 Nm, slightly above its frozen 1e-7 Nm gate. Its V2 normalized value remained 2.194610e-16; this historical run remains a failure and the gate was not changed.

## Mesh and participant independence

- The maximum structure-to-actual-cylinder-centroid tracking error across all successfully parsed time levels was 4.960318e-13 m.
- At OpenFOAM `t = 0.125, 0.150, 0.175, 0.200 s`, all three U and p hashes differ; the field norms also differ. The three raw `forces.dat` SHA256 values differ.
- Final `checkMesh` snapshots report no negative cells, min cell volumes of 0.001587458, 0.001584230, and 0.001587445, maximum non-orthogonality about 30.64 degrees, and maximum skewness about 0.5031.
- The run did not retain `checkMesh`-grade volume/non-orthogonality/skewness values at every time step. That observability requirement is therefore explicitly `FAIL`; no missing value is treated as a passing mesh-quality observation.

## Mapping and solver evidence

- Generalized Force Metric V2: `PASS` for all 20 corrections; maximum utilization 0.0367123.
- ANCF Newton evidence: `PASS`, 20 predictions plus 20 corrections.
- Force-chain and raw-force/adapter first-step reconciliation: `PASS`.
- The three fluid participants and the structure participant exited normally; 20/20 coupled windows committed.

## Scope conclusion

No VIV, lock-in, Strouhal, amplitude-convergence, or frequency-convergence conclusion is made from this 0.1 s startup smoke.
The formal smoke fails. The earliest chronological numerical hard gate is the V3 mesh-motion auxiliary solver-health failure at `tau = 0.015 s`; later failures include Courant, structural startup velocity, the frozen legacy absolute moment gate, and incomplete per-step mesh-quality observability. No longer calculation was started.
