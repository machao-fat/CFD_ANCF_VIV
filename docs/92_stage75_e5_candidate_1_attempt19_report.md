# Stage75 E5 candidate 1 attempt19

本次使用全新 run/runtime，从 Stage74 step559 只读 source 执行固定 4 blocks、40 steps（三 slice）。实际墙钟为 911.968 s（约 15 分 12 秒），完成 steps 560--599，生成 40 checkpoints、120 raw snapshots，终态为 `AUTHORIZED_WINDOW_COMPLETE`。

source SHA 前后均为 `341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`，未复用 attempt18 partial，未自动创建 step600 或后续 block；owned residual=0。

优化后的真实耗时相对此前约 16 分钟略有下降，但仍受 MATLAB/OpenFOAM/WSL 调度与环境波动影响，不能用离线 mock 速度替代真实测量。统计合同仍未满足：frequency、正式 Strouhal、稳定 VIV 与 lock-in 均保持未完成。

下一步必须获得新的明确授权后才能创建全新 segment；本次不启动任何后续 CFD。
