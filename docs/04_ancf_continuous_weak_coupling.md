# ANCF 连续单切片弱耦合

ANCF 使用已有三维两节点 Hermite ANCF 梁、Green 轴向应变和几何非线性曲率能。高张力、小变形配置与 EB 使用相同的 `D、EI、T0、dt、切片位置和 H/H^T`；CFD 重新独立运行，不把 EB 的最终载荷拷给 ANCF。

`results/04_single_slice_ancf_fsi_continuous_run2/` 已完成 1000 步连续闭环，记录 Newton 迭代、结构残差、预测/校正差、力、功率和 checkpoint。1000 步运行无 CFD 崩溃、无文件跳步、无 NaN/Inf。

审查规则：最小局部张力必须单独输出；出现持续负轴力时标记 `compression-risk`，不能通过放宽 Newton 容差掩盖。绝对机械能包含预张力参考常数，能量结论采用增量审计。
