# Stage 4E-B1-v3 persistent ANCF runner hardening report

## Scope

This closeout corrected the persistent runner startup exception boundary. Ordinary `Exception` paths are recorded and re-raised; cleanup is in `finally`; `KeyboardInterrupt` and `SystemExit` preserve their original exception and no implicit restart is allowed.

Lifecycle regression: 15/15 passed, including initialize timeout, worker exit, protocol error, stale response, `KeyboardInterrupt`, `SystemExit`, idempotent shutdown, retry rejection, unrelated-process protection, and PID creation-time mismatch refusal.

## Real MATLAB fail-fast

The MATLAB executable existed, and the read-only preflight found zero preexisting MATLAB processes after excluding PowerShell query commands. Exactly one version probe was started (PID 10936 with child PID 45736). It produced no usable version output and timed out. Both exact owned PIDs were closed; residual owned processes are 0. No smoke worker and no formal persistent ANCF test started.

This is an environment-blocked result, not a fabricated MATLAB result.

## Runtime hygiene

All task-controlled files are under `D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\stage4e_b1_v3\20260813T120904Z_7debb26b4e` on D:. The scoped variables `TEMP`, `TMP`, `TMPDIR`, `PYTHONPYCACHEPREFIX`, `PIP_CACHE_DIR`, `MPLCONFIGDIR`, and `MATLAB_PREFDIR` were task-local. No C-drive project artifact was created; no historical MATLAB process was terminated.
