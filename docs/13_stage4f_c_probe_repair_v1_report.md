# Stage 4F-C-v1 probe-repair report

## Scope and protection

This repair used only a new `stage4f_c_probe_repair_v1` source/test/runtime
namespace and `13_stage4f_c_probe_repair_v1` result namespace. Previous v3.1,
v3.1.1, v3.1.2 evidence and the Stage 4F-B-v5 parent evidence were read-only.
No protocol, frozen contract, threshold, geometry, domain, ANCF core, worker,
OpenFOAM case, or A/B/C branch was changed or started.

## Diagnosis

The v3.1 probe treated mixed `-logfile`/stdout text as its data source and used
substring/regular-expression checks. That permits display text such as
`R2021b` to be mistaken for the native `version('-release')` value and can
match an unrelated standalone `1` as the license result. The later structured
probe improved field naming but did not produce a payload when MATLAB failed
during ApplicationService initialization, leaving the failure indistinguishable
from a parser failure.

The repaired contract reads only `responses/probe_payload.json`, requires the
native values `release=2021b`, `architecture=win64`, and integer
`license_test_matlab=1`, rejects non-finite JSON and wrong variable names, and
checks all four D-drive temporary/pref paths. Launcher console and MATLAB
internal logs are separate; an optional structured console echo is checked only
for consistency and never used as the source of truth.

## Verification

Offline probe-repair tests: 10 passed. Related non-MATLAB Stage 4F regression:
26 passed. `python -m compileall -q src tests`: passed.

Exactly one real probe was launched. It used
`D:\Program Files\MATLAB\R2021b\bin\matlab.exe` with a D-drive runtime. MATLAB
returned `1` before writing the payload and reported MathWorks ApplicationService
error 5001. The result is therefore `environment_blocked`; no release/license
value is inferred from the failure log. Launcher, MATLAB core, and ServiceHost
identities are recorded in the event log; owned residual is 0 and C-drive
project artifact count is 0.

## Verification boundary

GUI manual verification is acknowledged as an external observation only. The
automatic probe did not pass. MATLAB worker verification and OpenFOAM/FSI
numeric verification were not started. Since the probe failed, the requested
`stage4f_three_slice_short_window_v1_attempt2` was not created and A/B/C were
not started.
