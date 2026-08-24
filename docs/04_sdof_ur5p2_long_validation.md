# Ur=5.2 长时间验证

## 案例和重启

未覆盖原 10 s 结果。案例从
`cases/openfoam/single_dof_free_viv_Ur5p2_corrected_source30_10s_clean`
的 10 s checkpoint 复制到独立 continuation，先运行到 32.5 s checkpoint，再切换到独立加速 continuation，最终在 60.0 s checkpoint 停止。运行期间删除了 checkpoint 之后未同步的 CFD 时间目录，并将审计 CSV 截断到 60.0 s。

结构参数为 `Ur=5.2`、`m*=10`、`zeta=0.01`、`dt=0.0025 s`，固有频率 `fn=0.1923077 Hz`，目标周期 `Tn=5.2 s`。共保留 24000 个结构时间步；以 8–60 s 计为 10 个完整周期。

## 安全性

- 最大 `|y|=0.43204 m < 1.5D`；
- 最大 CFL `0.17546 < 0.5`；
- 未见 NaN/Inf、负体积或时间错位；
- 60 s checkpoint 的 CFD 时间目录、结构 step 和时间均为 `step=24000, t=60 s`。

因此本次长算例是“数值安全完成”，不是“稳定 VIV 通过”。

## 两个相邻五周期窗口

| 指标 | 8–34 s | 34–60 s | 相对变化 |
|---|---:|---:|---:|
| 位移 RMS | 0.13998 m | 0.28146 m | 101.08% |
| 峰值位移 | 0.30538 m | 0.43204 m | 41.48% |
| `Fy` RMS | 220.58 N | 184.75 N | 16.24% |
| 平均功率 | 27.01 W | 38.36 W | 42.02% |
| `Cl` RMS | 0.4412 | 0.3695 | 16.24% |
| 响应频率 | 0.36282 Hz | 0.37631 Hz | 3.72% |

所有关键量均超过稳定窗口目标，`rolling_stability_pass=false`。逐周期流体功从 8.72 W 上升至约 43.05 W 后回落至 33.33 W，能量输入也未形成相邻周期平台。因此不能称为 10 周期稳态 VIV，也不能用该结果建立锁定曲线。

量化结果：`results/04_sdof_corrected_campaign/Ur5p2_long/steady_metrics.json`。
