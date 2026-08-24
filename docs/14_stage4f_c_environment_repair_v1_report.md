# Stage 4F-C environment-repair Gate report

Exactly one diagnostic run compared exactly one invocation of each requested
command shape. Both cases used D-drive `TEMP`, `TMP`, `TMPDIR`, `PREFDIR`, and
`MATLAB_PREFDIR`, and both preserved separate stdout, stderr, MATLAB logfile,
event log, process identities, and cleanup records.

The `-batch` form returned `1` and emitted repeated `Unable to load
ApplicationService` messages plus MathWorks error 5001 before the MATLAB
expression ran. Its launcher, MATLAB core, and ServiceHost descendants were
recorded and cleaned with owned residual 0.

The `-nosplash -nodesktop -nodisplay -r` form returned `0` at the outer launcher,
but produced no diagnostic markers, no MATLAB logfile, and no observed MATLAB
core or ServiceHost process. This is a launcher-only return and is not a
successful MATLAB headless diagnostic; treating it as success would recreate
the wrapper false-positive that this stage is intended to prevent.

Therefore both MATLAB internal diagnostics failed. The environment Gate is
`environment_blocked`; stop and request MATLAB Repair or reinstall. No strict
probe was re-executed, and no attempt2, worker, OpenFOAM, or Stage 4F-C A/B/C
branch was created or started.
