# Stage348 restart field-time correction

The Stage341 `80` directory has `uniform/time.value` near `80.0 s`, while its
boundary displacement matches mapping step `15999` at `79.995 s`. Stage348
will use a fresh runtime and materialize that saved field as `79.995`, set the
structure source identity to `15999/79.995 s`, and run a 41-step smoke to
`80.2 s`. Only a passing smoke may authorize the separate continuation to
`200 s`.

Stage347 failed evidence remains read-only. This preparation has started no
MATLAB, OpenFOAM, WSL, or CFD processes.
