# Stage 61 累计统计收口与 E4 后续入口评审

`STAGE4F_D_CUMULATIVE_STATISTICS_CLOSEOUT_V1_GATE: pass`。

本阶段纯离线完成。纳入的合法窗口为 Stage50 E2、Stage53 E3-A、Stage58 E4 segment1、Stage59 segment2 和 Stage60 segment3：合计 360 global steps、360 checkpoints、1080 raw snapshots，累计新增物理窗口约 0.45 s。各 campaign 的 source transition、tick、run/case/step/slice identity 和 lineage 保持显式边界；没有把不连续或不具备稳定窗口证明的数据强行拼接用于正式周期统计。

Stage52 partial 和 Stage56 block_4 越界现场明确排除，未纳入累计统计。统计合同保持 Stage54/55 原值：至少 15 个有效周期、300 个样本、三个稳定统计窗口、FFT/zero-crossing 差异不超过 5% 和升力幅值门槛。当前证据未建立可审计的 15 个有效周期与三窗口稳定性，故频率状态继续为 `not_evaluable_insufficient_cycles`；FFT/zero-crossing 仅可作 diagnostic，不输出正式 frequency、Strouhal、稳定 VIV 或 lock-in。

基于 Stage58–60 实测成本，后续 0.05 s、0.10 s、0.15 s 延拓分别约需 40/80/120 steps、960/1920/2880 s 和 0.56/1.11/1.67 GB，单段预算内，但达到 15 周期仍不能由现有窗口可靠保证。建议为 `enter_E4_segment4_pending_authorization`，必须获得新的明确授权；五 slice、九 slice、长时 VIV、锁定区和实验验证继续 `do_not_enter`。

离线测试：compileall 通过；Stage61 专项 4 passed；根目录 910 collected、909 passed、0 failure、0 error、1 skipped。全程未启动 MATLAB、OpenFOAM、WSL 或任何真实 CFD。
