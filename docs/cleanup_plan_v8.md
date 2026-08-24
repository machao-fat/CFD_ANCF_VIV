# Project cleanup plan v8

The read-only audit found 131.392 GB, 1059591 files and 173648 directories. The exact normalized deletion manifest contains 54459 targets (122.909 GB logical size).

OpenFOAM `0`, `constant` and `system` are protected. A manifest-only safety correction removed 86 accidentally proposed `0` time directories before execution. No project file was deleted.

| category | targets | bytes |
|---|---:|---:|
| openfoam_time | 54418 | 121.755 GB |
| old_figure | 24 | 1.154 GB |
| cache | 14 | 0.000 GB |
| build_artifact | 2 | 0.000 GB |
| temporary_file | 1 | 0.000 GB |

All targets are exact paths below the project root and are checked again by the single PowerShell deletion executor. Reparse points are not followed.
