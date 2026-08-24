# 阶段三补全完成报告

## 结论

本阶段结论为：**条件通过基础设施准入，但不通过物理准入；不得进入多切片**。

已完成并有可复核证据的内容：

- 阶段二遗留项审计和 CFD 配置冻结；
- `ancfFileMotion` 连续逐步文件读取、SHA-256/step/time 校验、有限等待和中途 latestTime 重启；
- 单步结构 runner 改为持久 MATLAB worker，EB/ANCF 统一请求/响应、predictor 回滚和 checkpoint；
- EB 与 ANCF 各自完成 1000 步连续单切片文件闭环到 `t=2.5 s`；
- EB `dt=0.00125 s` 的 200 步短复核完成；
- MATLAB EB 独立验证、CSV 协议测试、在线单步烟测和动网格库编译通过。

关键定量结果：在线规定运动断点续传最终完成 25000 步、62.5 s、10 个周期；与解析回放升力 RMSE 为 `14.09 N`、相对 RMSE `5.55%`，因此连续握手通过，但水动力“仅输出精度差异”只作条件通过。高张力在线 EB/ANCF 位移最大绝对差约 `2.25e-10 m`，但力相对 RMS 差约 `5.56%`，需在更有物理意义的柔性配置和 dt/2 下复核。

SDOF 代码和 Newmark 契约测试通过；Ur=3 已完成 4000 步、10 s，Ur=4 只完成约 1 s，Ur=5–7 尚无可接受统计窗口。五工况并发试验因 WSL 资源争用中止，已修复载荷监控器的 O(N²) 文件扫描，但五点锁定趋势尚未形成。因此 SDOF 物理验证不通过。

## 弱耦合判断

在当前高张力、小位移接口诊断中，响应有界、文件 step/time 无跳跃，EB 结构残差约 `8.7e-11`，ANCF 最大记录残差约 `0.826` 且 Newton 迭代不超过 3 次。可是 dt/2 短复核的平均功率和高张力能量增量尚未达到可接受的时间收敛/能量平衡证据，不能据此宣布弱耦合足够支撑 VIV 物理结论。

当前不强行实现 Aitken；先修正能量定义、完成五 Ur 统计和同工况时间收敛。若这些复核仍出现残差增长或能量不平衡，再进入固定松弛/Aitken 强耦合。阶段三未完成前禁止多切片、整根立管和机器学习。

证据索引：

- [阶段二欠项审计](04_stage2_debt_audit.md)
- [连续握手](04_continuous_handshake.md)
- [在线长周期回放](04_online_motion_long_replay.md)
- [EB 连续闭环](04_eb_continuous_weak_coupling.md)
- [ANCF 连续闭环](04_ancf_continuous_weak_coupling.md)
- [SDOF 验证](04_single_dof_viv_validation.md)
- `results/04_continuous_fsi/stage3_quantitative_summary.json`
## 最新补全记录（2026-08-04）

最终状态：**不通过**。已通过的是阶段二欠项复核后的接口基础设施、严格 native/file 在线运动等价、持久 EB/ANCF runner 契约与能量审计工具；未通过的是自由VIV稳定统计、多工况锁定曲线、同初始流场时间步收敛、可见稳定响应下 EB/ANCF 在线物理比较和完整 restart 等价。阶段三未完成前禁止进入多切片。

核心结果汇总见 `results/04_continuous_fsi/stage3_final_metrics.json`。
