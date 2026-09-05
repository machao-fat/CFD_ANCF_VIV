# Generalized Force Metric V2 Contract

Status: `PASS` before the fresh CFD run.  This contract is frozen in
[`generalized_force_metric_v2_and_0p1s_micro_smoke_v1_contract.json`](../../tools/generalized_force_metric_v2_and_0p1s_micro_smoke_v1/generalized_force_metric_v2_and_0p1s_micro_smoke_v1_contract.json).

For every ANCF node the generalized coordinate ordering is
`[r_x, r_y, r_z, r_sx, r_sy, r_sz]`.  Position coordinates have unit m and
slope coordinates `dr/ds` have unit 1 (m/m).  From `delta W = Q^T delta q`,
the conjugate generalized-load units are respectively N and N m.  C++ and
Python both store these as `double`; their unit is defined by the DOF index,
not by the storage type.

| DOF group | q unit | Q unit | absolute floor |
| --- | --- | --- | --- |
| position x/y/z | m | N | `2.842170943040401e-14 N` |
| slope x/y/z | 1 (m/m) | N m | `8.881784197001252e-14 N m` |

For each DOF `j`, the hard criterion is:

`abs(Q_cpp,j - Q_formal,j) <= atol_group + rtol * S_j`

where `S_j = sum_i abs((H_i^T F_i)_j)` over the three slices and
`rtol = 128 * epsilon = 2.842170943040401e-14`.  `S_j` is a contribution
scale, rather than `abs(Q_total,j)`, so positive/negative slice cancellation
cannot make the denominator ill-conditioned.  When `S_j = 0`, the appropriate
absolute floor is used; the zero-force regression separately requires exact
zero output.

The numerical margin is 128 ULPs: the immutable corrections 1--9 and the
expanded native C++ matrix (`zero`, single x/y/z, equal, unequal, mixed sign,
realistic, 0.01x, 0.1x, 10x, and 100x) observed at most
`3.691876147882848e-16` contribution-normalized difference.  Thus it gives
substantial cross-language rounding margin while remaining far below a true
mapping discrepancy.  The legacy mixed-unit `absolute_inf_error` is retained
only as a diagnostic and is not a hard gate.

