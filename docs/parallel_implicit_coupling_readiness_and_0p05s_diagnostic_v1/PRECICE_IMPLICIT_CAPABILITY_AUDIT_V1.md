# PRECICE_IMPLICIT_CAPABILITY_AUDIT_V1

- C++ preCICE library: `3.4.1`; Python binding available through the established dependency path: `3.4.0`.
- The deployed OpenFOAM adapter binary exports `requiresWritingCheckpoint`, `requiresReadingCheckpoint`, `writeCheckpoint`, `readCheckpoint`, volume/mesh checkpoint methods, and checkpoint-time restoration methods.
- The Python participant API exposes `requires_writing_checkpoint()` and `requires_reading_checkpoint()`.
- preCICE 3.4.1 accepted this parallel-implicit schema in `precice-config-validate`:

```xml
<coupling-scheme:parallel-implicit>
  <participants first="Structure" second="Fluid"/>
  <max-time value="0.05"/>
  <time-window-size value="0.005"/>
  <min-iterations value="2"/>
  <max-iterations value="8"/>
  <absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="1e-8" rel-limit="1e-5"/>
  <absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="1e-3" rel-limit="1e-5"/>
</coupling-scheme:parallel-implicit>
```

The existing explicit `structure_participant.py` contains no checkpoint callback. Therefore the installed capabilities are not yet an executable end-to-end implicit participant implementation. The fluid adapter's binary support remains `PENDING_RUNTIME_VERIFICATION` until an actual preCICE window proves mesh, fields, old-time levels, and physical time restore together.
