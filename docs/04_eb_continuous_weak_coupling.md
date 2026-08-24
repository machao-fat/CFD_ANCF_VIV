# EB 连续单切片弱耦合

EB 使用两节点三次 Hermite 梁、预张力几何刚度、一致质量、Rayleigh 阻尼和 Newmark 平均加速度。单切片载荷通过现有 H/H^T 协议写入 `slice_loads.csv`，未使用论文中简单均布力替代。

配置：二维 OpenFOAM 单切片、`dt=0.0025 s`、高张力 `T0=1e8 N`、`D=1 m` 的接口诊断配置。`results/04_single_slice_eb_fsi_run7/` 已完成 1000 步连续闭环，包含力、预测/校正运动、功率、结构残差、checkpoint 和 OpenFOAM 日志。

这组高张力配置的位移约为 `4.5e-10 m`，适合检查接口、时间戳、能量字段和网格稳定性，不足以作为柔性立管 VIV 振幅验证。后续是否接受弱耦合，以时间步减半和能量不平衡结果为准。
