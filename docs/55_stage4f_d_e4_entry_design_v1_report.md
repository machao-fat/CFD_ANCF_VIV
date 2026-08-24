# Stage 55 E4 bounded campaign 设计与授权评审

`STAGE4F_D_E4_ENTRY_REVIEW_V1_GATE: pass`。

本阶段仅完成离线设计和审计，未启动 MATLAB、OpenFOAM、WSL 或真实 E4 CFD。Stage 50 E2 约覆盖 0.10 s，Stage 53 E3-A 新增约 0.20 s；当前累计新增窗口约 0.30 s。Stage 53 accepted source 为 step 319、time 1.9075 s、tick 1907500000，SHA-256 为 `5cf040d090d1c57a4ac73cbbd7b3c59898ba1520db9aaa1b61ffaf3218323c8b`，前后保持一致；Stage 52 partial 未复用。

候选投影采用 Stage 53 实测吞吐率：E4-short 新增 0.10 s（80 steps/8 blocks，约 1920.6 s、1.11 GB）；E4-medium 新增 0.20 s（160/16，约 3841.2 s、2.22 GB）；E4-long 新增 0.30 s（240/24，约 5761.8 s、3.33 GB）；分阶段方案先执行 0.05–0.10 s，每段结束进行统计审计并由新授权决定是否延伸。上述成本均在单重型进程、4 小时和 20 GB预算内，但不能据此保证达到 15 个有效周期。

统计合同冻结为：至少 15 个有效周期、300 个样本、三个稳定窗口、FFT/zero-crossing 相对差异不超过 5%，并通过升力幅值门槛。任一条件失败均输出 `not_evaluable_*`，不得输出正式频率或 Strouhal。E4 仍不构成稳定 VIV、锁定区或实验验证。

推荐：`enter_E4_pending_user_authorization`。优先采用可分阶段停止的三 slice 方案；五 slice、九 slice、长时 VIV、锁定区及实验验证继续 `do_not_enter`。

离线测试：compileall 通过；Stage55 专项 3 passed；根目录 910 collected、909 passed、0 failure、0 error、1 skipped。
