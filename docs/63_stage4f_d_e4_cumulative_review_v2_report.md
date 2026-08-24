# Stage 63 E4 累计统计复核与后续入口决策

`STAGE4F_D_CUMULATIVE_STATISTICS_REVIEW_V2_GATE: pass`。

本阶段纯离线完成，未启动 MATLAB、OpenFOAM、WSL 或任何真实 CFD。纳入合法窗口为 Stage50 E2、Stage53 E3-A、Stage58/59/60/62 四个 E4 segments：合计 400 global steps、400 checkpoints、约 1200 raw snapshots，累计新增物理窗口约 0.50 s。各 campaign 的 source transition、tick、run/case/step/slice identity 和 parent lineage 保持独立且连续；未发现可证实的重复 tick、时间空洞、motion discontinuity 或 snapshot identity 冲突。

Stage52 partial 和 Stage56 block_4 越界现场明确排除，未纳入累计统计。正式统计合同保持不变：至少 15 个有效周期、300 个样本、三个稳定统计窗口、FFT/zero-crossing 差异不超过 5% 和升力幅值门槛。当前数据仍不能证明 15 个有效周期和三稳定窗口，故状态为 `not_evaluable_insufficient_cycles`；diagnostic FFT/zero-crossing 不升级为正式频率或 Strouhal。

基于实测吞吐率，segment5 约 40 steps、960 s、0.56 GB；segment5+6 约 80 steps、1920 s、1.11 GB；分阶段 E5 每段 0.05–0.10 s 并在段末复核统计。由于当前证据无法可靠保证达到 15 个周期，推荐 `enter_E5_staged_campaign_pending_authorization`，而非直接扩大 slice 或降低统计门槛。五 slice、九 slice、长时 VIV、锁定区和实验验证继续 `do_not_enter`。

离线验证：compileall 通过；Stage63 专项 4 passed；根目录 910 collected、909 passed、0 failure、0 error、1 skipped；真实外部进程启动数为 0。
