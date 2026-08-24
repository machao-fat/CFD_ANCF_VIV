# Stage 31 restart step identity repair failure

终态：`STAGE4F_C_RESTART_STEP_IDENTITY_REPAIR_V1_GATE: do_not_pass`。

离线 compileall、Stage 31 专项 2/2、Stage 30/29 合同测试和根目录 unittest 890/890 均通过。新 B_first 从原始父 checkpoint 独立运行 5/5，physical committed 与 fully audited 一致，owned 进程正常关闭。

首次修复已使 restart scheduler 恢复 source step=4、next expected step=5、source tick=1520000000、next tick=1522500000，原先的 `step must continue from 0, got 5` 不再出现。但第一笔 continuation checkpoint 在 commit validator 处失败：scheduler 未绑定 restart source 的 `_committed_checkpoint_path`，生成的 `parent_checkpoint_id` 为空，触发 `stabilized checkpoint parent identity is missing or invalid`。失败发生在任何新 committed step 之前，B_restart physical=0、audited=0。

本授权 attempt 按规则冻结，未在同一 runtime 重试，C 未启动。随后补充的 source-path 绑定修改只作为未执行的最小修复保留，不代表本 attempt 通过；Stage 30 旧结果和 Stage 23--29 证据均未修改。下一步需要新的隔离 attempt 验证 parent lineage 修复。
