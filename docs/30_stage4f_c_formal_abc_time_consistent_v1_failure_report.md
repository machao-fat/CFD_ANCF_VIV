# Stage 30 formal ABC failure report

终态：`STAGE4F_C_FORMAL_ABC_TIME_CONSISTENT_V1_GATE: do_not_pass`。

正式 A 从原始父 checkpoint 独立启动并完成 20/20 steps、20 个 committed checkpoints，physical 与 fully audited 一致。B_first 完成 5/5 steps、5 个 checkpoints，owned processes 正常关闭。

B restart 使用全新 case/runtime 和 B_first 的第 5 步 committed checkpoint。初始化在任何新 step 提交前失败，scheduler 报告 `step must continue from 0, got 5`。首个根因是 restart engine 构造后 scheduler 的内部 step identity 未从 checkpoint 恢复到 step 5。该失败不是 MATLAB、OpenFOAM、CFD、稳定化、mapping、UTF-8、整数或数值门槛失败。

按照冻结停止条件，B_restart 后续不重试，C 未启动。A/B_first 证据、B_restart partial case/runtime 和进程日志均保留；Stage 23--29 旧证据未修改。最小修复是让 restart loader 在接受 continuation step 前恢复 scheduler 当前 step，并在全新隔离 attempt 中重新执行 B restart；这属于 checkpoint/restart 生产接口变更，需新的独立授权。
