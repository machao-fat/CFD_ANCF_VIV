# MATLAB--C++ ANCF cross-validation V1

Status: `C++_ANCF_NUMERICAL_CORE_STATUS=PASS` for the frozen 50 m, 16-element,
zero-damping ANCF-only contract in
`results/validation_matlab_cpp_v1/phase_a_result.json`.

MATLAB R2021b was actually executed.  Both implementations use the same
geometry, material, fluid/gravity loads, top tension, constraints, Newmark
parameters, Newton tolerances, Gaussian integration orders, and analytic
initial perturbation `y=1e-4 sin(pi*s/L)` with matching nodal slopes.

Static equilibrium was evaluated at every node and every element midpoint.
The normalized L2 coordinate-shape error and maximum absolute coordinate
error were both zero at the recorded floating-point precision.

The first six transverse modes were paired by nodal-shape MAC, not merely by
index.  MATLAB / C++ frequencies (Hz) are:

| mode | MATLAB | C++ | relative error | MAC |
|---:|---:|---:|---:|---:|
| 1 | 0.198761026753895 | 0.198761026753869 | 1.32e-13 | 1.0 |
| 2 | 0.476181930710043 | 0.476181930710145 | 2.15e-13 | 1.0 |
| 3 | 0.870240169232574 | 0.870240169232566 | 9.44e-15 | 1.0 |
| 4 | 1.398512328182106 | 1.398512328181983 | 8.75e-14 | 1.0 |
| 5 | 2.068594917195311 | 2.068594917195309 | 1.07e-15 | 1.0 |
| 6 | 2.884283735124461 | 2.884283735124513 | 1.79e-14 | 1.0 |

Thus the approximately 0.20 Hz first transverse mode is independently
confirmed.  In the 50 s free response, all three stations have the same FFT
peak, 0.199900049974981 Hz; their displacement NRMSE is at most 3.44e-12 and
the maximum measured early-to-late phase drift is 1.37e-12 rad.  Mass,
internal-force and tangent comparisons also pass; the largest mass entry
difference is 9.09e-13, while static internal force and tangent are identical
at the emitted precision.

The acceptance criteria were frozen before execution: static normalized shape
error <= 5e-3, modal frequency relative error <= 5e-3, MAC > 0.95, dynamic
frequency relative error <= 5e-3, RMS relative error <= 2e-2, and time-series
NRMSE <= 2e-2.  All passed.  No C++ reconstruction deviation was found under
this contract.
