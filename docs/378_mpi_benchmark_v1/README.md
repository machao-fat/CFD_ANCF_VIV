# Stage 378: per-slice MPI benchmark

This stage compares the validated three-slice C++ worker + preCICE path with
one, two, and four OpenFOAM MPI ranks per slice. Every run is a fresh
`0 -> 0.2 s` window with 40 steps at `dt=0.005 s`, OpenFOAM 10, three slices,
and the persistent C++ worker. No MATLAB, E5, or long CFD run is part of this
stage.

The machine-readable result is `results/378_mpi_benchmark_v1/mpi_benchmark_comparison.json`.

All successful variants passed 40/40 structure commits, 40 quality records per
slice (including Courant), barrier/identity checks, zero returns, empty stderr,
and owned-residual=0. The same launcher was used for all variants. The initial
`three_serial` attempt is retained as a separate `do_not_pass` tool failure
because PowerShell/WSL PID escaping left empty wait variables; it is excluded
from performance numbers and was not retried in place.

Measured result:

| variant | ranks/slice | wall clock | speedup vs serial | efficiency |
|---|---:|---:|---:|---:|
| three_serial_v2 | 1 | 30.247 s | 1.000 | 100.0% |
| three_mpi2_v2 | 2 | 41.338 s | 0.732 | 36.6% |
| three_mpi4 | 4 | 41.216 s | 0.734 | 18.4% |

For this mesh, per-slice MPI is slower: MPI process/partition and preCICE
coordination overhead dominates. Keep the existing three-slice process-level
parallelism. Re-evaluate MPI only after a substantially larger per-slice mesh,
with a new short authorized benchmark and unchanged physical contract.

Gate:

```text
STAGE4F_D_MPI_THREE_SLICE_SHORT_BENCHMARK_V1_GATE: pass
```
