# Stage-3 v7 cleanup report

## Scope and safety

- Scope was restricted to `D:\研二文件\开题准备\CFD_ANCF_VIV`. No sibling directories, Zotero storage or other projects were touched.
- The read-only inventory was generated before cleanup at `results/cleanup/cleanup_inventory_v7.json`.
- No source, tests, formal docs, v7 evidence, case templates, checkpoints or committed scientific time series were deleted.
- Four uncommitted CFD time directories beyond the 221.25 s checkpoint were archived, checksum-verified and removed to recover synchronized restart state. Archive: `D:\研二文件\开题准备\CFD_ANCF_VIV\archives\stage3_v7\restart_overshoot_after_221p25.zip`.

## Inventory and operations

- Inventory scope size before regenerable-cache deletion: 3.548 GiB (generated/reparse/high-volume trees are represented by directory summaries).
- Regenerable cache files deleted: 0 files, 0.000 MiB.
- Archived restart-overshoot directories removed: 4 directories; archive size 3.803 MiB.
- Net released-space estimate including the archived overshoot: 5.773 MiB.
- Archive SHA-256: `f365d2af7f9dab1322713855a0f772e80bb926ca0d4bd1f30e09bc50cca3b04a`.
- Archive entry random read: passed before deletion.

## Retention

`retained_critical_files_v7.json` records source, tests, formal reports, v7 JSON/figures, SDOF/EB/ANCF checkpoints and OpenFOAM case templates. The cleanup is reversible for the archived restart overshoot through the ZIP archive; Python caches are regenerable.

## Post-cleanup validation

The post-cleanup read-only validation record is `results/cleanup/post_cleanup_validation_v7.json`; status: **PASS**. It covers Python regression, MATLAB regression, v7 JSON existence, strict figure validation, single-slice template integrity and checkpoint readability. The archived restart directories remain recoverable through the ZIP archive.
