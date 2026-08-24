# Stage-3 v7 cleanup read-only audit

- project root: `D:\研二文件\开题准备\CFD_ANCF_VIV`
- audit is read-only; no files were archived or deleted
- files: 88416
- total size: 3.548 GiB

| state | files | size (GiB) |
|---|---:|---:|
| DELETE_REGENERABLE | 42 | 0.000 |
| DO_NOT_DELETE | 372 | 0.002 |
| KEEP | 153 | 0.341 |
| REVIEW_REQUIRED | 30982 | 3.205 |

## Safety rule

Only exact absolute paths inside the project root may be archived/deleted after explicit retention review. The project root itself, source, tests, formal docs, v7 JSON/figures, final campaign data, OpenFOAM templates/checkpoints and restart evidence are retained. Any uncertain numeric OpenFOAM time directory is REVIEW_REQUIRED.
