# Project cleanup report v8

## Final decision

**清理完成，阶段三可复核，阶段四原型准入资格保持有效**

## Capacity and deletion

| item | before | after |
|---|---:|---:|
| logical size | 131.392 GB | 8.532 GB |
| file count | 1059591 | 675651 |
| directory count | 173648 | 10328 |
| drive used | 560.224 GB | 436.389 GB |

- Logical bytes released: **122.860 GB**.
- PowerShell execution: 54459/54459 targets, failures 0.
- No project-related compute process was running; no long CFD calculation was run.
- The post-cleanup Python regression recreated 20 small `__pycache__` directories. They are rebuildable test artifacts and were not removed in a second destructive process, in accordance with the single-PowerShell deletion rule.

## Deleted categories

| category | targets | logical size |
|---|---:|---:|
| openfoam_time | 54418 | 121.755 GB |
| old_figure | 24 | 1.154 GB |
| cache | 14 | 0.000 GB |
| build_artifact | 2 | 0.000 GB |
| temporary_file | 1 | 0.000 GB |

## Retained evidence

The full `src/`, `tests/`, `docs/`, OpenFOAM base configurations, v8 JSON/CSV evidence, final PNG/SVG/PDF figures, v8 dt/dt2 checkpoint branches and checkpoint hash manifest remain. The v8 stage3 metrics still report `stage3_fully_passed=true` and `eligible_for_stage4_prototype=true`.

Checkpoint hash verification: 688 present hashes matched; failures: 0.

Python regression retained: 50/50; MATLAB result retained as a verified v8 10/10 record and was not rerun during cleanup.

## Twenty largest remaining directories

| rank | size | directory |
|---:|---:|---|
| 1 | 8.532 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV` |
| 2 | 6.870 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases` |
| 3 | 6.870 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam` |
| 4 | 5.292 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended` |
| 5 | 2.299 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_discretization_run2` |
| 6 | 1.632 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\results` |
| 7 | 1.575 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_forced_extended` |
| 8 | 1.067 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_discretization_run2\near_shedding_fine_Euler` |
| 9 | 0.860 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_forced_extended\below_shedding_forced` |
| 10 | 0.757 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_discretization_run2\near_shedding_medium_backward` |
| 11 | 0.716 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_forced_extended\near_shedding_forced` |
| 12 | 0.714 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\results\04_sdof_corrected_campaign` |
| 13 | 0.475 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_discretization_run2\near_shedding_medium_Euler` |
| 14 | 0.474 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_dynamic_mesh_comparison_run4` |
| 15 | 0.350 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_dynamic_mesh_comparison_run3` |
| 16 | 0.336 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\fixed_cylinder_study` |
| 17 | 0.297 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\prescribed_motion_extended\prepared_dynamic_mesh_comparison_run2` |
| 18 | 0.203 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\results\03_prescribed_motion_extended` |
| 19 | 0.202 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\results\04_eb_ancf_long_time_comparison_v5` |
| 20 | 0.180 GB | `D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\fixed_cylinder_study_full30b` |

## Scope boundary

No physical model, solver, acceptance threshold or stage3 evidence was changed. No multi-slice, full-riser or stage4 computation was started. See `results/cleanup/post_cleanup_validation_v8.json` for the machine-readable validation result.
