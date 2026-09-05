# Phase 3 — Read-only local V3 analysis, 220–370 s

The historical V2 analysis averaged the three retained y coordinates before
forming structural statistics. V3 leaves Stage385 intact and instead reads the
two continuous retained segments (Stage381 and Stage382) at their existing
0.05 s scalar cadence. For each slice it analyzes:

- `Fy = pressure_y + viscous_y` from the slice `forces.dat`;
- `y` from `interface_positions_xy[i][1]`; and
- `vy` from `interface_velocities_xy[i][1]`.

Source inspection establishes that `project_interface()` returns projected
**positions**, then velocities. The historical writer calls the first return
value `displacement_xy` when it writes preCICE. Thus V3 explicitly labels the
retained `y` series as an absolute projected ANCF y coordinate, not a
separately verified displacement from static equilibrium.

V3 computes local signal statistics, FFT and peak frequencies, Welch
cross-spectra/coherence at 0.16 and 0.20 Hz, raw-scale `Fy*vy` diagnostics,
and slice-slice beating diagnostics. The power quantities are deliberately not
Watts: Stage381/382 lack `unit_span_m` and tributary length, so force scale and
physical work remain `not_evaluable`.

The V3 gate separates data integrity, mathematical mapping conservation,
local stationarity, local flow/structure synchronization, slice-phase
diagnostics, and physical force scale. It never treats fixed slice-to-slice
phase as a prerequisite for local statistical convergence.

For the retained 220–370 s data, V3 finds local `Fy` near 0.16005 Hz and all
three local y coordinates near 0.20007 Hz. The local `Fy`–y coherence at the
nearest Welch bins to 0.16/0.20 Hz is only about 0.002–0.004. Local amplitude
and FFT-frequency drift pass the predeclared 5% retrospective diagnostic, but
that does not establish lock-in. The maximum retained relative moment mapping
error is `4.44e-10`, above the required `1e-10` mapping threshold, so the V3
mapping-integrity section is intentionally `fail`; no threshold was relaxed.

Reproduce:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python tools/solver_validation_v3/reanalyze_historical_v3.py
python -m unittest tests/solver_validation_v3/test_three_slice_statistics_v3.py
python -m unittest tests/solver_validation_v3/test_historical_v3_evidence.py
```

The resulting V3 evidence records all source hashes. It does not write under
`runtime/` or `results/385_three_slice_statistical_contract_v2_phase_reanalysis_v2/`.
