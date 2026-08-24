# 阶段三修复状态：movingWall 审计后

本次复核没有沿用旧的自由 VIV 结论。旧的 `noSlip`/动壁面边界不一致、圆柱 patch 不一致、长算例在约 6.89 s 出现 CFL 爆炸，以及旧 checkpoint 与物理修复后的案例不兼容，均已标记为 invalid。旧 Ur=5.2、Ur=6.0、dt 对比和旧锁定趋势不进入本报告。

## 已执行

| 项目 | 结果 | 证据 |
|---|---|---|
| `s_ref_m` 协议 | 通过 | publisher、load CSV、ready marker 均强制校验；SDOF 为 0 m，横流切片为 75 m；协议单元测试 19/19 |
| movingWall 固定圆柱 200 步 | 条件通过 | `results/04_moving_wall_smoke/fixed_retry`；CFL 0.1291，201 个力样本，几何体积/偏斜度正常 |
| movingWall 规定运动 200 步 | 条件通过 | `results/04_moving_wall_smoke/prescribed_retry`；CFL 0.1325，运动与力有限；`checkMesh` 仍报告预期二维 edge-alignment 诊断 |
| 修正源场 Ur=5.2，dt=0.0025 s | 仅筛查通过 | 10 s 完成，无 CFL 爆炸；统计窗口仅 0.9615 个周期 |
| 修正源场 Ur=5.2，dt=0.00125 s | 仅筛查通过 | 10 s 完成；与粗步长的位移 RMS、力 RMS、平均功率变化分别为 12.40%、6.39%、10.84% |
| EB/ANCF 横流在线 100 步 | 通过接口烟测 | 两个分支均 CFL<0.5、投影守恒、Newton 收敛、张力为正 |
| EB/ANCF 横流在线 10 s | 趋势通过、物理准入未通过 | 同网格、同时间步、独立 CFD；全程约 1.55 个一阶周期，不足 2–3 周期 |
| native/file restart | 未通过严格准入 | 场变量在 0.5 s/1 s 相同到约 1e-7/2e-8，但重启后前两个力样本最大差约 0.3204 N；`restart_checked=false` |

## 当前判断

接口和单切片结构分支已经具备可审计的连续运行能力，但阶段三仍为“不通过”。原因不是 ANCF/EB 小变形差异，而是：修正 SDOF 尚未形成 10 周期稳定窗口；时间步差异仍超过目标；严格 restart 等价性未通过；五点锁定曲线尚未重新计算。禁止进入多切片。
