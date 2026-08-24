# Stage 4E-B2-A-v2.3 high-Re URANS restricted pilot

## Execution identity

- run_id: 20260816T183000000Z_stage4e_route1_plus_2_v2_3_luna_retry2
- case: fresh high_kOmegaSSTLM_medium_N
- solver: OpenFOAM 10 pimpleFoam
- model: kOmegaSSTLM, scenario N
- mesh: 5120 cells, 10624 points, 20672 faces
- fixed dt: 0.0001 s
- production interval: 2.0--9.0 s

The 10-step preflight returned zero, contained End, and had max CFL 0.4300124169618181. Four continuation blocks completed with return code zero and End. The maximum production CFL in the block logs was 0.161800268921469; no online hard-stop event occurred. Exact registered solver PIDs were used for lifecycle accounting. Failed input attempts remain in their run directories.

## Production statistics

The force history contains 14001 samples from 2.0 to 9.0 s at a 0.0005 s sampling interval. Production mean Cd is 1.036844424196114 and Cd fluctuation RMS is 1.545072260405823e-05. Cl fluctuation RMS is 3.612128141846208e-05 and Cl peak-to-peak is 0.0004681701130734888. The three windows show Cl fluctuation RMS decay: 6.75466911636872e-05, 1.9875634135074193e-06, and 1.6638157990325785e-07.

The lift signal is below the frozen 0.001 evaluability threshold and non-stationary. Diagnostic FFT and zero-crossing peaks are recorded but are not promoted to dominant frequency, zero-crossing frequency, St, or effective cycles. frequency_status=not_evaluable_low_amplitude and effective_cycles=0.

## Integrity checks

Raw force and forceCoeffs agree exactly at the recorded floating-point values in the 14001-point production cross-check; maximum relative error is 0.0. Solver-generated yPlus fields were preserved at five endpoints; cylinder-patch p95 y+ is about 0.22236 at production endpoints, below the 1.0 target. ReThetat, gammaInt, k, omega, and nut are finite at all audited endpoints.

## Scope result

The engineering status is rejected_low_amplitude, not a physical failure of the Route 1 methodology. Scenario S and fine were not authorized because the medium-N frequency/stationarity gate was not met. No nine-slice CFD or experimental claim follows from this pilot.
