# Stage 4F-C environment-repair diagnostic

This independent diagnostic compares exactly one `-batch` launch and exactly
one `-nosplash -nodesktop -nodisplay -r` launch. Both use D-drive TEMP, TMP,
TMPDIR, PREFDIR, and MATLAB_PREFDIR. Each attempt has separate stdout, stderr,
MATLAB logfile, event records, process identities, and cleanup actions.

No probe-repair v1 evidence, parent evidence, frozen contracts, thresholds,
geometry, domains, ANCF core, workers, OpenFOAM, or Stage 4F-C A/B/C content is
modified by this diagnostic.
