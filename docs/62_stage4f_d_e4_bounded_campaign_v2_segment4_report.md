# Stage 62 E4 segment4 最终报告

`STAGE4F_D_E4_BOUNDED_CAMPAIGN_V2_SEGMENT4_GATE: pass`。

本段从 Stage 60 最后 accepted checkpoint step 439、time 2.0575 s、tick 2057500000 分叉，使用全新 runtime、case、exchange 和 process registry，严格完成 4 blocks/40 steps（step 440–479），时间范围约 2.05875–2.1075 s。生成 40 个 unified committed checkpoint 和 120 个三 slice raw snapshots，parent lineage 从 Stage60 step439 连续至 step479。

最大 CFL=0.0599333751654754，最大 raw |Cd|=1.29860846204136，最大 velocity consistency=3.30940376843583e-06，最大 virtual-work relative error=4.26387248478601e-16，force conversion error=0，最大 geometry error=8.32667268468867e-17 m。墙钟 993.219 s，磁盘 555564875 bytes，预算内。

最后授权 step 479 后进入 `AUTHORIZED_WINDOW_COMPLETE`；未创建 block_4、step_480、额外 checkpoint 或 snapshot，未启动 segment5。

source checkpoint SHA 前后保持 `37d303835f9d60df5f05af0a700dcefc64517885b20b87b77af6887e379c151e`。Stage50–61 旧证据未修改，Stage56 block_4 越界现场和 Stage52 partial 未复用。

累计统计诊断累计至约 400 global steps、1200 raw snapshots，但正式统计合同要求的 15 个有效周期、300 样本、三个稳定窗口和 FFT/zero-crossing 一致性仍未完整满足，故继续为 `not_evaluable_insufficient_cycles`。不输出正式 frequency、Strouhal、稳定 VIV、lock-in 或实验验证结论。

前置 compileall、Segment-4 专项（2 passed）和根目录回归（910 collected、909 passed、0 failure、0 error、1 skipped）均通过。
