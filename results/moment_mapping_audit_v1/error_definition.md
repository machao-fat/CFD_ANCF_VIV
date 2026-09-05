# Legacy moment-error definition

`src/coupling/stage303_interface_mapping_repair_v1/canonical_projection.py`
defines the retained historical scalar as

`abs(fluid_moment_z - mapped_moment_z) / max(abs(fluid_moment_z), abs(mapped_moment_z), 1e-30)`.

The origin is the global `(0,0,0)` and the scalar is the z component of the
planar cross product `r_x F_y - r_y F_x`, in N m before normalization.  It is
a relative metric only when the resultant moment is well conditioned.  It
does not report either absolute moment, the sum of absolute individual moment
contributions, or a reference-point transformation identity.

The V1.2 analytical audit adds a future-only, versioned metric:

`||M_fluid - M_mapped|| / max(sum_i ||r_i-origin|| ||F_i||, 1 N m)`

and always retains the corresponding absolute error.  This definition is
well conditioned for a pure couple or cancellation.  It does not alter
legacy Stage341--385 records or their frozen fail decision.
