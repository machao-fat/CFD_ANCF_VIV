# Stage348 restart field time preparation

Stage341 directory `80` contains a `uniform/time` value of approximately
`80.0 s`, but its boundary displacement matches mapping step `15999` at
`79.995 s`. A correct continuation must materialize the fields in a fresh
`79.995` directory, set the OpenFOAM source identity to global step `15999`,
and advance one coupling step to `80.0 s` before normal continuation.

This stage only audits and specifies that transformation. It does not copy or
modify the Stage341 runtime and does not start MATLAB, OpenFOAM, WSL, or CFD.
