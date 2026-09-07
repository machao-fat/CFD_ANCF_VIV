# SAME_BASELINE_EXPLICIT_IMPLICIT_0P05S_DIAGNOSTIC_V1_REPORT

## Frozen baseline

- Git commit: `1390f34f9395b115a3fbb66a4700e5e0e144175f`; dirty at freeze: `True`.
- Adapter: `/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib/libpreciceAdapterFunctionObject.so`, SHA256 `6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`; upstream `d53753b1c927b2413b02299c9da15725b3e772f0`; patches `['0001-respect-adapter-target-dir', '0002-diagnostic-rollback-fingerprints', '0004-registry-safe-rollback-and-motion-timing', '0005-precice-time-layer-and-different-input-rollback']`.
- Both cases use `PRECURSOR_STATE_V1`, no-flow equilibrium, dt=0.005 s, OF time 0.100→0.150 s, Quality V4, and Generalized Force V2. The only intended variable is coupling scheme.

## Run status

- parallel-explicit: committed `10/10`; final OF time `0.15` s; immutable launcher gate `FAIL`; first blocker `unique_wire_ids`.
- parallel-implicit: committed `1/10`; final OF time `0.105` s; immutable launcher gate `FAIL`; first blocker `CPP_WORKER_PROTOCOL_FAILURE_AFTER_COMMITTED_WINDOW_1`.
- Explicit read-only completion re-audit: `PASS`; checks `{'structure_completed': True, 'all_participants_returned_zero': True, 'unique_correction_wire_ids': True, 'physical_horizon_recorded': True, 'quality_v4': True}`.

## Evidence and comparison

- Common committed coupling times [s]: `[0.005]`.
- At tau=0.005 s, both committed structural records have the same raw force: `Fx=1248.2039243948773 N`, `Fy=-45.96578643732784 N` per slice, and the same integrated slice force: `Fx=20803.398739914624 N`, `Fy=-766.0964406221308 N` (within slice-length roundoff).
- The implicit force function-object file did not flush before its participants were stopped; its committed structural record is the authoritative source for that final committed force and is explicitly marked as such in the JSON ledger.
- Algorithmic interface work (not a physical-energy claim), explicit [J]: `[-36.22367868592168, -58.39517751417607, -36.03307887252886]`; implicit [J]: `[0.0, 0.0, 0.0]`.
- Explicit maxima by slice: `[{'slice_id': 0, 'max_abs_raw_Fx_N': 25494.296038142802, 'max_abs_raw_Fy_N': 1462.92230440706, 'max_abs_ux_m': 0.00106839481936207, 'max_abs_uy_m': 1.5064772385519487e-05, 'max_abs_vx_mps': 0.1264063973488198, 'max_abs_vy_mps': 0.006210839619716466}, {'slice_id': 1, 'max_abs_raw_Fx_N': 17997.2495624316, 'max_abs_raw_Fy_N': 1193.63853625468, 'max_abs_ux_m': 0.0010944477185549654, 'max_abs_uy_m': 1.4361916106309763e-05, 'max_abs_vx_mps': 0.10357362688335751, 'max_abs_vy_mps': 0.004112682917179157}, {'slice_id': 2, 'max_abs_raw_Fx_N': 25549.408053824303, 'max_abs_raw_Fy_N': 1465.7368049075098, 'max_abs_ux_m': 0.0010644143314432282, 'max_abs_uy_m': 1.5063370312453781e-05, 'max_abs_vx_mps': 0.1265121303903562, 'max_abs_vy_mps': 0.006236043048293995}]`.
- Implicit maxima over its sole committed window: `[{'slice_id': 0, 'max_abs_raw_Fx_N': 1248.2039243948773, 'max_abs_raw_Fy_N': 45.96578643732784, 'max_abs_ux_m': 1.6641630090056396e-05, 'max_abs_uy_m': 6.128370530956172e-07, 'max_abs_vx_mps': 0.006656652036022559, 'max_abs_vy_mps': 0.00024513482123824694}, {'slice_id': 1, 'max_abs_raw_Fx_N': 1248.2039243948773, 'max_abs_raw_Fy_N': 45.96578643732784, 'max_abs_ux_m': 1.5604141886979283e-05, 'max_abs_uy_m': 5.746309873704121e-07, 'max_abs_vx_mps': 0.006241656754791713, 'max_abs_vy_mps': 0.00022985239494816484}, {'slice_id': 2, 'max_abs_raw_Fx_N': 1248.2039243948773, 'max_abs_raw_Fy_N': 45.96578643732784, 'max_abs_ux_m': 1.6642842857299692e-05, 'max_abs_uy_m': 6.128817139070551e-07, 'max_abs_vx_mps': 0.006657137142919876, 'max_abs_vy_mps': 0.0002451526855628221}]`.
- Explicit Quality V4 summary: `{'0': {'status': 'pass', 'max_courant': 0.366904149058, 'max_abs_continuity_global': 2.64976253234e-09, 'auxiliary_efficiency_status': 'warning', 'pimple_terminal_convergence': 'pass'}, '1': {'status': 'pass', 'max_courant': 0.364225586017, 'max_abs_continuity_global': 2.16614023431e-09, 'auxiliary_efficiency_status': 'warning', 'pimple_terminal_convergence': 'pass'}, '2': {'status': 'pass', 'max_courant': 0.367004089827, 'max_abs_continuity_global': 2.65488459139e-09, 'auxiliary_efficiency_status': 'warning', 'pimple_terminal_convergence': 'pass'}}`.
- Implicit Quality V4 summary: `{'0': {'status': 'pass', 'max_courant': 0.350303474526, 'max_abs_continuity_global': 1.98763663389e-11, 'auxiliary_efficiency_status': 'pass', 'pimple_terminal_convergence': 'pass'}, '1': {'status': 'pass', 'max_courant': 0.350303474526, 'max_abs_continuity_global': 1.98763663389e-11, 'auxiliary_efficiency_status': 'pass', 'pimple_terminal_convergence': 'pass'}, '2': {'status': 'pass', 'max_courant': 0.350303474526, 'max_abs_continuity_global': 1.98763663389e-11, 'auxiliary_efficiency_status': 'pass', 'pimple_terminal_convergence': 'pass'}}`.
- Explicit Newton and Generalized Force V2 evidence are complete for 10/10 windows. The implicit one committed window has passing Newton and V2 records; the 10-window aggregate is incomplete because the worker disconnected before window 2.
- The explicit immutable launcher gate is FAIL only because its one-window-oriented audit required two correction wires per physical window and final adapter-trace data that parallel-explicit does not create. The read-only re-audit checks the correct explicit evidence: correction wire sequences 2,4,...,20, final recorded horizon, Quality V4, and all four participant return codes. It does not alter the immutable gate.
- The implicit first blocker is a C++ worker protocol disconnection (worker return code 16) immediately after the first committed window, before window 2's prediction response. It is an infrastructure/IPC lifecycle failure, not a fixed-point nonconvergence or Quality V4 failure.
- Classification: `INFRASTRUCTURE_FAIL`. `NEXT_SHORT_TIME_EXTENSION=NOT_AUTHORIZED`.

## Scope

- This is a short numerical coupling comparison only. It makes no VIV, lock-in, long-time amplitude, or added-mass conclusion.
- No run longer than the two authorized 0.050 s cases was launched; this report was generated by read-only post-processing.
