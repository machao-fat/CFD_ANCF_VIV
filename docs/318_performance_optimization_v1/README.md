# Stage318 performance optimization

The Stage317 moving-mesh smoke measured the actual baseline before any
optimization. The dominant cost was repeated `cellDisplacementx/y` solution:
five PIMPLE outer iterations per step caused 80 mesh-motion solves in eight
steps, and 26 of those reached 1000 iterations.

This stage prepares an isolated safe candidate configuration:

- fix `cacheAgglomeration` spelling;
- preserve the validated mesh update schedule (`moveMeshOuterCorrectors yes`);
- retain `deltaT 0.005 s`, five PIMPLE outer correctors, physics, thresholds,
  and three slices;
- write fields every 10 steps in binary format.

The candidate is not applied to a real solver in this stage. Run the offline
comparison with:

```powershell
$env:PYTHONPATH = "src"
python tools/performance_optimization_v1/run_offline_benchmark.py
```

The report distinguishes measured baseline values from predicted reductions.
A separate aggressive candidate with `moveMeshOuterCorrectors no` was tested in
Stage319 and rejected because the mesh did not move. A new explicit
authorization is required for Stage320 to measure the safe candidate wall-clock
and verify displacement, force, virtual-work, and mesh-quality equivalence.
