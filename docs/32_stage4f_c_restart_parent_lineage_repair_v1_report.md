# Stage 32 B restart parent lineage repair

终态：

`STAGE4F_C_RESTART_STEP_IDENTITY_REPAIR_V1_GATE: pass`

`RESTART_STEP_IDENTITY_STATUS: accepted`

`BRANCH_B_RESTART_STATUS: accepted_pending_C_reauthorization`

`BRANCH_C_STATUS: not_started_by_scope`

Stage 31 的首次分叉在 fresh restart engine 创建后：scheduler 已恢复 source step/tick，但未绑定 source checkpoint，因此新 checkpoint 的 `parent_checkpoint_id` 为 null。Stage 32 让 restart engine 将 source checkpoint 绑定到 scheduler 的 committed checkpoint path，并传递 committed step/time/tick。离线测试 2/2 通过。

新 attempt 使用 run_id `stage32_formal_B_parent_lineage_v1`，B_first 为 5/5（step 0--4，1.5100--1.5200 s），B_restart 为 15/15（step 5--19，1.5225--1.5575 s）。source step 4 的 tick 为 1520000000，restart current step=4、next step=5；首个 restart checkpoint parent 为 `checkpoint_step00000004_367ddd0d13ce`。总计 20/20 physical committed 且 fully audited，20 个 checkpoint，parent lineage 连续，60 个 immutable raw snapshots 完整。

硬门槛审计：max CFL `0.1363270394859547`；max raw/applied `|Cd|` `2.6846025735776475` / `2.6846025735776475`；max velocity consistency `0.00034745809305939605`；max virtual-work relative error `3.7615106790949934e-16`；force conversion `0`；max geometry error `8.326672684688674e-17 m`。UTF-8、mtime_ns、tick、run/case/transaction identity、tau `0.023728053952574758` 和 canonical contract hash `cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78` 均通过。

owned process 共 100 个（MATLAB 40、WSL/OpenFOAM 60），return code 全为 0，evidence complete，residual 0。父 checkpoint SHA-256 保持 `5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e`。Stage 23--31 旧结果和 Stage 31 失败证据未修改。Stage 32 证据位于 `results/32_stage4f_c_restart_parent_lineage_repair_v1/`，包括 Gate、lineage、snapshot、process 和 hash audit JSON。C 未启动；下一授权点仅为 C 的独立授权。
