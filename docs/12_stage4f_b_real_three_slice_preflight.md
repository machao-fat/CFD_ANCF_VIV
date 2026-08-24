# Stage 4F-B Real Three-Slice Low-Re Preflight

Status: **blocked after real-CFD force-scale audit**.

The three-slice `0.2.1` transaction completed three global steps with a real
OpenFOAM 10 `pimpleFoam` process per slice and a real MATLAB R2021b ANCF
predictor/corrector.  All three committed checkpoint manifests validate and
the maximum reported CFL is `0.1720630064`.

This is not an accepted CFD--ANCF preflight. At step zero, with prescribed
global `x/y` motion exactly zero, OpenFOAM reported `F_OF,x=306074.686 N` on
a one-metre span.  For `rho=1000 kg/m3`, `U=1 m/s`, and `D=1 m`, the force
scale is `0.5 rho U^2 D=500 N/m`, hence `Cd=612.149`. The independent static
warm-up on the same mesh ends at `F_x=838.163 N` and `Cd=1.67633`.

The length conversion is not the cause. The formal payload has
`F_i=F_OF*(16.6666667/1)` exactly once, and the actual H/H^T virtual-work
relative residual is `2.0646e-16`. The failure occurs in the raw dynamic CFD
force before coupling integration. The new dynamic case is seeded from a
static state and lacks a consistent dynamic `Uf`, `meshPhi`, and `phi` restart
state. That startup inconsistency creates a pressure spike even without
transverse motion.

No restart, additional steps, five/nine-slice run, VIV statistic, lock-in
analysis, or experimental validation was attempted after the hard stop.
