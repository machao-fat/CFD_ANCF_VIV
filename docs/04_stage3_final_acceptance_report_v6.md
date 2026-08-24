# Stage-3 final acceptance report v6

## Decision

Stage 3 is **conditionally passed and remains open**. The v6 response-cycle method resolves the nominal-window ambiguity and verifies Ur=5.2 robustly, but the formal five-point gate is not satisfied because the following evidence remains outside the final steady criterion: Ur4 response-cycle stationarity not passed, Ur8 response-cycle stationarity not passed, five-point formal gate remains closed.

## Evidence

- Ur=5.2 ends at 130.000 s and passes 3/3 late pairs.
- All SDOF safety limits pass: True.
- The frequency fix is covered by the v6 response-cycle tests; the old v3 doubled values are obsolete.
- EB/ANCF continuation status: physical acceptance ready = True; common end time = True; mesh hash match = True; comparison = {"y_rms_relative_difference": 0.0012642175875599488, "y_peak_relative_difference": 0.0007116806055055985, "half_amplitude_relative_difference": 0.0007973052977244647, "frequency_relative_difference": 0.0, "fy_rms_relative_difference": 7.946875921176142e-05, "mean_power_relative_difference": 0.0010150552680290134}.
- Python v6 regression: pass with 38 tests. MATLAB 10/10 is inherited from the v5 run and is not silently counted as a new execution.

## Weak coupling and scope

The single-slice weak-coupling diagnostics do not provide a current reason to make Aitken a mandatory v6 gate. This does not authorize multi-slice extrapolation: no multi-slice or full-riser physical validation is claimed.

## Stage-4 entry

Stage-4 entry is **not approved**. The project must first close the listed v6 blockers; it must not enter multi-slice work while the formal five-point gate is open.
