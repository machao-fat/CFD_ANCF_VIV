# Stage75 E5 candidate 1 attempt11 report

## Gate

`STAGE75_E5_CANDIDATE_1_GATE: pass`

唯一授权 segment 已完成并进入 `AUTHORIZED_WINDOW_COMPLETE`。未启动 segment5、E5-C 或任何其他研究 campaign。

## 执行结果

- 4/4 blocks，40/40 steps，step 560--599；
- 40 checkpoints，120 raw snapshots，40 physical committed，40 fully audited；
- 时间 2.20875--2.2575 s，tick 2208750000--2257500000；
- lineage：Stage74 step559 -> Stage75 step560 -> step599 连续；
- source SHA 前后均为 `341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`；
- 停止门控：未尝试 block4、step600 或自动延拓；owned residual=0。

最大指标：CFL `0.05860025483009841`，raw `|Cd|` `1.6077517397599164`，velocity consistency `4.012686012359445e-06`，virtual-work relative error `4.1445913842130606e-16`。

预算：墙钟 `999.905999999999 s`，新增磁盘 `555056875 bytes`，均在合同内。

## 统计复核

累计统计样本约 480（按三 slice 展开），但至少 15 个有效周期和三个稳定窗口仍未证明；FFT/zero-crossing 仍仅为 diagnostic。因此保持：`frequency=not_evaluable_insufficient_cycles`、`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。

本阶段之后必须等待新的明确授权；不得自动延拓，五/九 slice、长时 VIV、锁定区和实验验证继续禁止。
