# Repository scope

This repository tracks the solver implementation, coupling adapters, build and
launch scripts, tests, reproducibility templates, and engineering notes.

Generated or reproducible artifacts are intentionally kept out of Git:

- OpenFOAM time directories, `postProcessing`, `VTK`, `processor*`, `coupling`,
  and generated meshes;
- runtime workspaces, temporary files, profiling traces, and caches;
- compiler outputs, Fluent transcript/log files, and other local run output;
- vendored/public reference datasets that have their own provenance or license.

For a published result, record the source commit, case configuration, solver
parameters, and the external location or archive identifier of the generated
data. Do not commit credentials, local absolute paths, or transient exchange
files.
