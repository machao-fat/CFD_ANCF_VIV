# Residual workspace cleanup v8

This cleanup used one PowerShell process with `ErrorActionPreference = Stop` and exact paths below the project root.

- Project root: `D:\研二文件\开题准备\CFD_ANCF_VIV`
- Before: 7.946 GB logical, 675652 files, 10328 directories.
- Deleted: 220 exact targets, 0 GB logical.
- After: 7.946 GB logical, 675474 files, 10288 directories (before this audit's own output files).
- Deletion failure: none

## Deleted categories

- zero_diagnostic: 180 targets, 0 GB
- empty_directory: 20 targets, 0 GB
- cache: 20 targets, 0 GB

## Protected items

- `tests/continuous_handshake/__init__.py` was retained as a Python package marker.
- `src/`, `tests/`, `docs/`, final v8 evidence and checkpoint hash manifest were not deletion candidates.
- Reparse points under `src/openfoam/ancfFileMotion/lnInclude` were skipped and preserved.
- No long-time CFD, multi-slice case or physical-model change was performed.

## Machine-readable records

- `results/cleanup/residuals_pre_inventory_v8.json`
- `results/cleanup/residuals_delete_manifest_v8.csv`
- `results/cleanup/residuals_deleted_v8.csv`
- `results/cleanup/residuals_post_inventory_v8.json`
- `results/cleanup/residuals_validation_v8.json`
