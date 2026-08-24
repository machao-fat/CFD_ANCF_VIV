# Stage 4F-B-v3 Equilibrated Startup Closeout

The v3 static ANCF equilibrium under the measured dynamic-hot-start mean load
passes the existing strain, tension and residual gates.  Its maximum lateral
position is nevertheless 0.3873 m, so it cannot be imposed instantaneously
on a dynamic mesh initialized at zero displacement.

A separate, real 0.05 to 0.55 s smooth dynamic-mesh reconciliation was run
for slice 0 only.  The solver completed without CFL or finite-value failure,
but the endpoint drag coefficient was 11.516, above the frozen short-gate
limit of 10.  The campaign stops before slices 1/2 and before formal FSI.

The next task must reassess the relationship between the selected mean-drag
baseline, the static equilibrium contract, and the bounded CFD domain.  It
must not simply relax the Cd limit or continue the remaining slices.

