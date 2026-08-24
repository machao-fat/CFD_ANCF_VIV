# Stage 64 E5 staged campaign 入口设计

`STAGE4F_D_E5_STAGED_ENTRY_DESIGN_V1_GATE: pass`。

本阶段纯离线完成，未启动 MATLAB、OpenFOAM、WSL 或任何真实 E5 CFD。Stage62 accepted 末端 source 为 step 479、time 2.1075 s、tick 2107500000，实际 checkpoint SHA 为 `3e100d2572bc9495cce1a5c3ba143a270f92b0139a5cb2cd1f4c0f5326ee8e4c`；Stage52 partial 和 Stage56 block_4 越界现场均排除。

E5-A 设计为新增 0.05 s、40 steps、4 blocks，预计墙钟约 993 s、磁盘约 0.56 GB；只有 E5-A 完整通过且统计状态未恶化，才可在新的授权下考虑 E5-B（再 0.05 s）。E5-C 为 0.05–0.10 s 分段停止方案。所有候选均是“可执行”而非“可统计评价保证”，不能声称能够达到 15 个有效周期。

统计合同保持 Stage54/55 冻结值：至少 15 个有效周期、300 个样本、三个稳定窗口、FFT/zero-crossing 差异不超过 5% 和升力幅值门槛。任一失败输出 `not_evaluable_*`，不得生成正式 frequency、Strouhal、稳定 VIV 或 lock-in。

唯一推荐：`enter_E5_A_pending_user_authorization`。每段使用全新 run/case/runtime，最后授权 step 进入 `AUTHORIZED_WINDOW_COMPLETE`，不自动延拓；硬门槛、身份、lineage、预算或统计状态恶化均 fail-closed。五 slice、九 slice、长时 VIV、锁定区和实验验证继续 `do_not_enter`。

离线测试：compileall 通过；Stage64 专项 3 passed；根目录 910 collected、909 passed、0 failure、0 error、1 skipped；真实外部进程启动数为 0。
