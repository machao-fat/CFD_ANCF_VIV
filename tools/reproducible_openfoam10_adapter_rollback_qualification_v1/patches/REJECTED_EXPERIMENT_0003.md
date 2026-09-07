# Rejected experiment: early meshPhi checkpoint registration

Patch `0003-openfoam10-checkpoint-lifecycle-and-motion-timing.patch` is kept
only as immutable diagnostic evidence. It unconditionally called
`setupMeshCheckpointing()` at a window-start checkpoint. In Foundation OF10,
this calls `fvMesh::phi()` before the first `fvMesh::movePoints()` has created
the mesh flux object and therefore fatals. It must not be applied by any
future default or qualification build.

Fresh failed runtime:
`runtime/openfoam10_checkpoint_lifecycle_motion_timing_closure_v1_run_001`.
