# Euler-Bernoulli FEM comparator

This directory is an independent small-displacement/small-rotation comparator for the phase-one ANCF model.

The global nodal order is `[u, theta_u, v, theta_v]`. Each plane uses a two-node cubic Hermite element. The implementation includes consistent mass, bending stiffness, frozen pre-tension geometric stiffness, consistent distributed loads, `H^T` integrated-slice force mapping, Rayleigh damping, Newmark average acceleration, energy audit fields, and checkpoint/restart.

The end constraints fix only transverse positions at the bottom and top. End slopes remain free, matching the ANCF x/y position constraints. The EB branch has no axial degree of freedom; `z_m` in its motion CSV is the reference arc length and non-zero `Fz` is rejected.

`pretension.mode='ancf_initial_balance'` uses the same effective submerged weight as `ancf_base_load` and `T(s)=T_top-w_sub*(L-s)`, with `s=0` at the bottom. `pretension.mode='paper_formula'` retains the thesis-style analytic profile with an independently configurable submerged unit weight for audit/comparison.
