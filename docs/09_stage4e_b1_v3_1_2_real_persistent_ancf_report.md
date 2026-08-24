# Stage 4E-B1-v3.1.2 真实 persistent ANCF 报告

真实 R2021b worker smoke：`passed`。initialize、predict、correct、Newton、有限状态、checkpoint、第二 worker 加载均完成；checkpoint 重启最大相对误差为 `0.0`，阈值为 `1e-11`。

四项真实协议测试按顺序执行并全部通过：checkpoint restart、direct state/transaction semantics、duplicate/stale response rejection、worker exit detection without silent restart。所有 worker 由 `session.start()` 进入，owned residual 为 0。

本报告不构成九切片真实 CFD、Stage 4E 整体、自由 VIV 或锁定区完成声明。
