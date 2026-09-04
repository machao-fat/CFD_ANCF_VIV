# Stage 2 O-grid prescribed-motion mesh

This is an independent replacement for the failed Fluent v2 mesh. It does not
modify the three-slice solver or any previous evidence.

## Geometry

- Single cylinder, `D=1 m`, centered at `(0,0)`.
- Far field rectangle: `x=[-5,10] m`, `y=[-5,5] m`.
- Structured O-grid annulus: `r=0.5..2.5 m`, 8 sectors, 12 radial intervals.
- Outer zone: stationary/deforming far field outside `r=2.5 m`.
- Physical groups: `cylinder`, `motionInterface`, `movingFluid`, `outerFluid`,
  `inlet`, `outlet`, `upper`, `lower`.

The intended Fluent setup is a moving near-field cell zone and a separate
outer zone. The interface is shared geometrically; Fluent dynamic mesh must be
configured and checked before any production run.

## Generation

```powershell
powershell -ExecutionPolicy Bypass -File `
  "D:\研二文件\开题准备\CFD_ANCF_VIV\tools\stage2_prescribed_motion_v1\generate_ogrid.ps1"
```

The generated mesh is written to
`D:\CFD\stage2_prescribed_motion_ogrid_v1\stage2_ogrid.msh` in MSH 2.2
format. The generator first writes a candidate mesh, rejects any Gmsh `Error:`
output, runs Gmsh's coherence check, and runs an independent audit for required
physical groups, duplicate coordinates/elements, isolated nodes, and degenerate
line or 2-D elements. Only then is the candidate promoted to the canonical
filename. The prior file, if any, is preserved with a `preexisting` timestamp
suffix. The JSON audit is stored beside
the mesh as `stage2_ogrid.audit.json`.

## Smoke gate

1. Import the mesh into Fluent 2D if possible; do not use the failed v2 case.
2. Confirm the O-grid annulus is a separate `movingFluid` zone and the outer
   region is `outerFluid`.
3. Load and attach `stage2_cylinder_motion` before enabling dynamic mesh.
4. Run 5 steps at `dt=0.0025 s` and inspect minimum cell volume.
5. Only if those 5 steps pass, run the remaining 395 steps to `t=1 s`.

Any negative volume, missing UDF callback, non-finite force, or missing report
sample is a fail-closed result. Do not continue from a failed state.
