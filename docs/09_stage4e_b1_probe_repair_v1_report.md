# Stage 4E-B1 probe-repair-v1

## Read-only root cause

The v3.1 logfile parser assumed line boundaries that MATLAB did not preserve,
and v3.1.1 then required `release_R2021b` even though MATLAB's native
`version('-release')` is exactly `2021b`. The v3.1.2 result corrected only the
old payload offline and did not launch MATLAB. The repaired stage writes and
validates a structured JSON payload, so stdout and logfile text are diagnostic
only.

## Real probe outcome

The independent offline contract tests passed before the real launch. The one
authorized repaired probe was then launched from a D-drive runtime. MATLAB
returned code `1` during ApplicationService initialization with error `5001`
before writing its payload. Five owned PID/creation-time records were observed
and all five were already exited during exact cleanup; no OpenFOAM process or
attempt2 branch was started. The result is therefore an honest environment
block, not a parser pass and not an ANCF/CFD result.

No old result, report, parent evidence, formal contract or ANCF core was
modified. A new authorization is required after the current-user MathWorks
ApplicationService state is repaired; the next probe must still be a single
fresh launch with the unchanged contract.
