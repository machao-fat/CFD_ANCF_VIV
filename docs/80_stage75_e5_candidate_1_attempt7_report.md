# Stage75 candidate 1 attempt7 report

`STAGE75_E5_CANDIDATE_1_GATE: do_not_pass`

本次授权 segment 在 block0/step520 的 OpenFOAM seed 阶段 fail-closed。没有提交 physical step、checkpoint 或 raw snapshot，未进入任何后续 block，也没有重试 attempt7。

根因是底层 case skeleton 仍从旧的 `START_TIME_S=1.5075` 生成 `controlDict` 和 `dynamicMeshDict`；restart source step559 的合法当前时间是 2.2075 s，因此 `ancfFileMotion` 报 `motion_ready is stale or time/payload does not match CFD time`。Stage74 source SHA 前后保持 `341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`。

已完成离线修复：`_prepare_case_skeletons`、`run_segment` 和 D2 diagnostic engine 现在显式传递 restart `start_time_s`，并同步 RuntimeConfig、controlDict、dynamicMeshDict 和 scheduler。compileall 通过，restart bridge 专项 13 passed。

attempt7 runtime 只读封存，未复用。该授权窗口已结束；Stage75 不得自动重试。需要新的明确授权后，才能使用全新 run/case/runtime 重新申请一个 segment。正式统计状态保持未完成。
