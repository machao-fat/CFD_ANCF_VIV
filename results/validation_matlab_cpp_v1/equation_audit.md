# MATLAB--C++ ANCF equation audit (V1)

Scope: the protected MATLAB implementation in `src/structure_ancf_matlab` and
the C++ kernel in `src/coupling/cpp_worker_persistent_ipc_v1`.  This audit is
source-based; numerical evidence is recorded separately in
`phase_a_result.json`.

| Item | MATLAB evidence | C++ evidence | Status |
|---|---|---|---|
| Two-node 3-D ANCF element / 12 local DOF | `ancf_shape.m`, block `N` | `shape`, `block_matrix` | MATCH |
| Hermite `H` | `ancf_shape(...,0)` | `shape(...,0)` | MATCH |
| `H_s`, `H_ss` | `ancf_shape(...,1:2)` | `shape(...,1:2)` | MATCH |
| Consistent mass | `ancf_mass_matrix.m`, fixed five-point Gauss | `make_reference_state`, `mass_gauss_order=5` | MATCH |
| Green-strain/bending energy | `ancf_internal_force_tangent.m` | `element_force_tangent` | MATCH |
| Internal force and analytic tangent | `element_analytic` | `element_force_tangent` | MATCH |
| Gravity / buoyancy | `ancf_base_load.m` | `static_base_load` | MATCH |
| Top tension | top `z` translation force | top `z` translation force | MATCH |
| Constraints | bottom xyz, top xy | canonical boundary `[0,1,2,6E,6E+1]` | MATCH |
| Global assembly / DOF order | six DOF per node, MATLAB 1-based | six DOF per node, C++ 0-based | MATCH (index-origin only) |
| Internal-force Gauss order | frozen 3 | frozen 3 | MATCH |
| Distributed-load quadrature | 3-point rule | 5-point rule | DIFFERENT_BY_DESIGN, analytically equivalent here because the cubic shape-weighted constant line load is integrated exactly by both |
| Newmark | beta=0.25, gamma=0.5 | beta=0.25, gamma=0.5 | MATCH |
| Static Newton | 40 ramps, 40 iterations, 0.8 relaxation, `1e-8` | same frozen values | MATCH |
| Dynamic Newton tolerance | `1e-8` | `1e-8` | MATCH |
| Linear solve accumulator | MATLAB double | C++ long-double elimination then double state | DIFFERENT_BY_DESIGN; equations and acceptance tolerance unchanged |
| Rayleigh damping | alpha=beta=0 | alpha=beta=0 | MATCH |
| Initial `q/qdot/qddot` | common static state plus analytic y perturbation / zero velocities and accelerations | same | MATCH |

No suspicious or blocked equation item remains for this frozen 50 m / 16
element comparison.  The original MATLAB source was not modified.
