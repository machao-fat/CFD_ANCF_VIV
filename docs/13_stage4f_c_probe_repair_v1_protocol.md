# Stage 4F-C-v1 probe-repair protocol

This is an independent environment gate. Existing Stage 4F-C-v1 attempt1
evidence, parent Stage 4F-B-v5 evidence, protocol 0.2.1, frozen contracts,
thresholds, geometry, domains, and ANCF core are read-only inputs.

The MATLAB payload file is authoritative. `launcher_console.log` contains only
launcher stdout/stderr; `matlab_internal.log` is MATLAB's `-logfile` output.
No console text is used to infer release, architecture, or license. A probe is
passed only when the payload has `release=2021b`, `architecture=win64`,
`license_test_matlab=1`, finite JSON, D-drive TEMP/TMP/TMPDIR/PREFDIR, an exact
R2021b executable, zero return code, successful ApplicationService payload,
complete owned process cleanup, and zero C-drive token artifacts.
