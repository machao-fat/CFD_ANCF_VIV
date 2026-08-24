# Stage 4F-D E5-A bounded campaign v1 最终报告

## Gate

`STAGE4F_D_E5_A_BOUNDED_CAMPAIGN_V1_GATE: pass`

唯一终态为 `AUTHORIZED_WINDOW_COMPLETE`。本阶段未启动 E5-B/E5-C 或其他 campaign。

## Source 与合同

- source：`checkpoint_step00000479_cb25680360ce`
- source step/time/tick：479 / 2.1075 s / 2107500000
- source SHA-256（前后）：`3e100d2572bc9495cce1a5c3ba143a270f92b0139a5cb2cd1f4c0f5326ee8e4c`
- Stage 64 segment contract SHA-256：`100fac81eeb0d67fa2738859352a752e456dd183e5a9864458142ba521474b95`
- 授权窗口：4 blocks × 10 steps，step 480–519，tick 2108750000–2157500000。

## 执行结果

- 4/4 blocks，40/40 physical committed，40/40 fully audited。
- 40 个 unified committed checkpoints，120 个唯一 raw snapshots；parent lineage 连续。
- 时间范围：2.10875–2.1575 s。
- step 519 后进入 `AUTHORIZED_WINDOW_COMPLETE`；未创建 block_4 或 step_520，未生成额外 checkpoint/snapshot。
- 最大 CFL：0.05922647784069305。
- 最大 raw |Cd|：1.3667530558620755；最大 applied |Cd|：1.2508659048709583。
- 最大 velocity consistency：4.759345001497003e-06。
- 最大 virtual-work error：4.118521086155227e-16。
- 最大 force conversion error：0。
- 最大 geometry error：8.326672684688674e-17 m。
- 墙钟：925.609 s；磁盘：555575684 bytes，均在冻结预算内。
- owned process：200 started / 200 closed / residual 0；非零返回 0。

## 统计与 claim boundary

合法累计样本增至 440，但仍未建立至少 15 个有效周期，三个稳定窗口也未满足。因此 `FREQUENCY_EVALUABILITY_STATUS=not_evaluable_insufficient_cycles`。诊断 FFT/zero-crossing 不提升为正式频率或 Strouhal。

- `FORMAL_STROUHAL_STATUS=not_completed`
- `STABLE_VIV_RESPONSE_CLAIM=not_completed`
- `LOCK_IN_CLAIM=not_completed`
- 五/九 slice、长时 VIV、实验验证均保持禁止进入。

## 测试

- compileall：通过。
- Stage 65 专项：2 passed，0 failure，0 error，0 skipped。
- Stage 57–64 离线回归：21 passed，0 failure，0 error。
- 根目录：910 collected，909 passed，0 failure，0 error，1 skipped，247.882 s。
- 首次日志管道包装层在 unittest 输出完整 `OK` 后未自动退出；精确关闭包装 session。权威无管道复跑再次输出完整 `OK`，测试 owned residual 为 0。

## 下一授权点

E5-B 仅具备申请资格，必须取得新的明确授权；当前不得自动启动。
