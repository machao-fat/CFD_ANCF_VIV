# 阶段三 EB/ANCF 横流向可见响应修复与离线对照

## 结论

EB/ANCF 的“同一横流向载荷、可见小变形响应”离线诊断已经通过；在线 CFD–结构物理对照仍未验收。本轮得到的峰值位移约为 `0.0132D`，比旧结果的 `1e-10 m` 高约八个数量级，且 EB/ANCF 后半段时程相对 RMSE 为 `6.31e-4`。该结果证明两套结构分支在一致参数、同一 `Fy` 和小变形条件下可以重合，但不能替代在线自由 VIV、锁定区或整根立管验证。

## 旧算例为什么无效

旧在线算例采用 `L=1 m, D=1 m, dInner=0.9 m, E=207 GPa, T=1e6 N`。它等价于长度仅为一个直径的厚壁短构件，弯曲和张力刚度都很高，因此 `1e-10 m` 量级响应只适合作为接口烟测。

直接把 `E` 降至 `207 MPa` 的尝试仍保留了顺流向自由度。平均阻力没有先建立静态平衡，随后在 `t=0.0125 s` 产生 `Fx=2.61e7 N`，下一预测状态达到 `x=0.148 m, vx=76.5 m/s`，最终出现 `CFL=7.75` 和 `SIGFPE`。当时横流向响应仍很小，所以这不是 ANCF/EB 横流向大变形能力的证据，而是未平衡顺流向运动导致的动网格失稳。

## 本轮发现并修复的两个结构一致性问题

### 无体力 runner 的预张力不一致

在线 comparator 会关闭重力和浮力。ANCF 因此只保留均匀的顶张力，但 EB 在构造模型时已经缓存了浸没重度形成的预张力梯度。`L=1 m` 时差异不明显，扩大到真实 `L/D` 后会成为显著误差。

现在无体力 runner 同时把 EB 的 `pretension.ancf_initial_weight_Npm` 置零，并增加了 EB/ANCF 参考张力一致性回归。默认 `eb_ttr_case` 和 `vertical_ttr_case` 的生产语义没有改变。

### EB 有阻尼 Newmark 右端项错误

由

```text
qdd = a0 (q - q_pred)
qd  = qd_pred + a1 (q - q_pred)
```

代入动态平衡后，正确离散方程为

```text
(K + a0 M + a1 C) q
  = Q + a0 M q_pred + C (a1 q_pred - qd_pred)
```

旧代码使用了 `C*(a1*qd_pred)`。在阻尼为零时该错误被隐藏；阻尼非零时会生成不满足动态平衡的 EB 响应。修复前，同一载荷下 `t=2 s` 的 EB/ANCF 位移为 `0.00655/0.000839 m`；将阻尼设为零后立即变为 `0.000846302/0.000846320 m`。修复后，有阻尼和无阻尼 Newmark 回归的相对动态平衡残差分别为 `1.57e-13` 和 `1.26e-13`。

## 离线同 Fy 对照设计

本算例没有任意降低材料弹性模量，而是通过合理的细长比获得可分辨响应：

| 参数 | 数值 |
|---|---:|
| 长度 `L` | 150 m |
| 外径/内径 | 1.0/0.9 m |
| `L/D` | 150 |
| 弹性模量 | 207 GPa |
| 顶张力 | 1.0 MN |
| 单元/切片 | 10/1 |
| 切片位置 | 75 m |
| 时间步/总时长 | 0.01/40 s |
| 公共载荷 | `Fx=Fz=0`, `Fy` 幅值 100 N |
| 载荷频率 | 0.165 Hz |
| 平滑加载时间 | 10 s |
| 一阶目标阻尼比 | 1% |

两个分支均关闭体力并采用均匀顶张力。若恢复当前几何对应的浸没重度，估算单位浸没重约 `3594 N/m`、底端张力约 `0.461 MN`，仍为正值。这项计算只是参数合理性审计，本轮并没有把体力加入离线对照。

结构质量与排水流体质量比约为 `1.455`，并不等于 SDOF 基准的 `m*=10`。因此该算例只验证 EB/ANCF 结构分支一致性，不用于复现文献锁定曲线。

## 定量结果

| 指标 | EB | ANCF | 差异 |
|---|---:|---:|---:|
| 一阶频率 | 0.1549978 Hz | 0.1549908 Hz | `4.56e-5` 相对差 |
| 峰值横向位移 | 0.0132361 m | 0.0132331 m | 约 `3e-6 m` |
| 后 20 s 位移 RMS | 0.00788055 m | 0.00787914 m | — |
| 后 20 s 时程相对 RMSE | — | — | `6.31e-4` |
| 最终最大斜率 | `2.6647e-4` | `2.6630e-4` | 小变形范围 |
| 最大顺流向位移 | 0 | 0 | 投影精确 |
| ANCF 最大相对 Newton 残差 | — | `9.86e-9` | 通过 |

所有离线诊断门槛均通过：可见响应、横流向投影、一阶频率差、时程 RMSE 和 ANCF Newton 收敛。

## 横流向在线接口准备

`continuous_fsi_driver.py` 新增了保持默认兼容的 `load_mode`：

- `full`：保持原有行为；
- `transverse_only`：原始 CFD 力仍写入审计，但送入 EB/ANCF 的结构载荷严格为 `[0,Fy,0]`。

审计文件同时保存原始 `force_*_N` 和实际 `applied_force_*_N`。这能避免把被排除的平均阻力误写成结构输入，同时保留完整 CFD 力证据。投影单元测试覆盖 EB、ANCF、默认兼容性和非法模式失败。

## 尚未完成的在线物理门槛

下一次在线短算例必须从完全相同的 CFD 初场分别运行 EB 和 ANCF，并满足：

1. 使用 `transverse_only`，确认 `x=0` 且 `applied_Fx=0`；
2. 使用相同结构几何、质量、张力、阻尼、切片位置和时间步；
3. 响应显著高于接口容差，并保持小变形；
4. 最大 CFL、网格质量、力和位移全程有界；
5. 分开报告原始 CFD `Fy` 是否因两套运动产生差异，不能把独立在线 CFD 说成“同一 Fy”；
6. 如需严格同一 `Fy`，只能使用本轮离线回放证据；
7. 在线 A/B 通过后仍只能称为单切片结构分支对照，不能称为整根立管 VIV 验证。

此外，当前 `publish_load_from_forces.py` 把载荷 CSV 的 `s_ref_m` 固定写为 `0.0`，而既有结构 runner 常使用 `0.5 m`。载荷协议目前只校验 `slice_id`，所以旧算例没有因该元数据差异停止，实际结构映射仍采用 runner 内的坐标；但这不满足严格协议审计。为避免与正在进行的 restart/耦合修改冲突，本轮没有改动 publisher。统一修复时应给 publisher 增加显式 `--s-ref-m`，由 continuous driver 传入，并让 load contract 同时校验 `slice_id` 与 `s_ref_m`。

## 证据文件

- `results/04_eb_ancf_physical_comparison/offline_transverse_same_fy/offline_transverse_same_fy.csv`
- `results/04_eb_ancf_physical_comparison/offline_transverse_same_fy/offline_transverse_same_fy_metrics.json`
- `tests/structure_runners/run_offline_transverse_comparison.m`
- `tests/structure_eb_fem/test_eb_damped_newmark.m`
- `tests/continuous_handshake/test_transverse_load_projection.py`
