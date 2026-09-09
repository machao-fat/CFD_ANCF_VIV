# Shiels S5-K9.88 单切片自由 FSI 一个周期有限延伸

## 结论

`SHIELS_S5_K9P88_SINGLE_SLICE_FREE_FSI_ONE_PERIOD_EXTENSION_V1 = PASS_FOR_BOUNDED_EXTENSION`。

本次运行从已通过的首次有限接入终态 `OF 0.155 s` 继续，以相同的
Foundation OF10 owner-diagnostic ABI、Adapter、网格、流体设置、`dt=0.005 s` 和
parallel-implicit min/max `2/8`，完成 `0.155 -> 5.155 s` 的 1000 个新接受窗口。
没有修改质量、刚度、阻尼、PIMPLE、耦合算法或物理参数。

该结果覆盖约 `5/4.46978 = 1.12` 个真空自然周期，说明启动阶段的单切片自由反馈
在本受控时间范围内可连续推进；它不是稳态 VIV、lock-in、网格/时间步收敛或长期
稳定性证明，也不扩展为 C++ ANCF 或 50 m 立管资格。

## 中断重试的证据边界

首个延伸 runtime `run_001` 保持不可变。它在 OF `3.930 s`、第 755 窗口提交后停止，
第 756 窗口只写入第一 trial；没有 `returns.txt` 或结构 summary。Windows 事件显示
WSL2 虚拟机在同一时间段被关闭；`fluid.stderr` 和 `participant.stderr` 均为空，最后
CFD 日志没有 FPE、负体积、solver fatal 或 preCICE 错误。因此该目录的状态是
`INCOMPLETE_RUNTIME`，不是数值 PASS，也没有用它改写任何历史 gate。

按用户授权建立了独立 `run_002`，使用完全相同的父终态和合同。运行以脱离终端的
launcher 启动，避免承载层再次在中途关闭；这只改变进程承载方式，不改变求解语义。

## 重启状态与合同

父运行是
`runtime/shiels_s5_k988_single_slice_free_fsi_first_trial_v1_run_002`，其最终接受状态为：

| 状态 | 值 |
|---|---:|
| CFD/结构时间 | `0.155 s` |
| `y` | `-2.415883995499957e-6 m` |
| `v` | `-6.988598307452067e-5 m/s` |
| `a` | `-1.0436023332462269e-3 m/s2` |
| 已接受窗口 / trial / restore | `10 / 30 / 20` |
| 上一接受横向力 | `-2.620940300053 N` |
| 父接口输入与结构状态差 | `3.6234470363e-9 m`，低于耦合绝对限 `1e-8 m` |

续算复制了父 case 的 `0.155` 时刻 `U/p/phi/Uf/meshPhi`、位移场、points 和
`uniform/time`；preflight 对每个文件做了 SHA256 相等性检查，且未使用人工相容
`Uf` 反事实。SDOF 包装层恢复了接受的 `y/v/a/step/time`、上一接受力与累计能量账本。
无 CFD 的续算单测中，step `10 -> 11` 的 restore 重放状态差为 `0`。

## 运行结果

| 指标 | 结果 |
|---|---:|
| 进程返回 | `structure=0 fluid=0` |
| 新接受窗口 | `1000/1000`，最终 `5.155 s` |
| trial / restore | `3000 / 2000` |
| 每窗口迭代 | 全部 3 次，满足 `[2,8]` |
| 最大 |y| | `2.7878814174e-3 m` |
| 最大 |v| | `2.3224729337e-3 m/s` |
| 最大 |Fy| | `10.1298730591 N` |
| 最大 Co | `0.345007184896`，低于 `0.5` |
| 最大全局连续性 | `1.26013934185e-11`，低于 `1e-8` |
| 几何误差 | 最大 `9.5087826502e-13 m` |
| pointDisplacement 误差 | 最大 `4.9964372917e-15 m`，80 个 cylinder 顶点 |
| 力身份 | 每个时间层与 participant 总力一致，最大差约 `1.14e-13 N` |
| 能量账本 | 累计流体做功 `0.0101357134913 J`；累计缺陷 `-2.6227529833e-17 J` |
| CFD / 网格质量 | 无 FPE、负体积或 forbidden token；最终标准 `checkMesh: Mesh OK` |

详细逐窗口数据保存在：
`results/shiels_s5_k988_single_slice_free_fsi_one_period_extension_v1_run_002/first_trial_result.json`。
该 JSON 包含 1000 个时间层的 accepted `y/v/a`、输入位移、压力/黏性/总力、耦合迭代、
网格/字段误差和能量累计；原始 preCICE/CFD 日志仍保留在对应 runtime。

## 响应形态与限制

在 `0.155 -> 5.155 s` 内，位移从父终态的小量负值发展到正向峰值后回落；全程没有
containment crossing 或求解硬失败。由于只有约一个自然周期，不能从该数据计算统计
稳定的幅值、频率、升力 RMS、平均阻力、相位锁定或 Shiels 表 2 的稳态响应
(`A/D=0.57`, `fD/U=0.198`, `CL` 振幅 `1.35`, 平均 `CD=2.23`)。
无阻尼结构的机械能变化按流体做功解释，不能套用自由衰减的恒能量判据。

## 资格与后续边界

```text
SHIELS_S5_K9P88_SDOF_FREE_DECAY_V1 = PASS
SHIELS_S5_K9P88_SINGLE_SLICE_FREE_FSI_FIRST_TRIAL_V2 = PASS_FOR_BOUNDED_FIRST_TRIAL
SHIELS_S5_K9P88_SINGLE_SLICE_FREE_FSI_ONE_PERIOD_EXTENSION_V1 = PASS_FOR_BOUNDED_EXTENSION
NEXT_SINGLE_SLICE_FREE_FSI = PENDING_MULTI_CYCLE_PHYSICAL_VALIDATION_PLAN
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

后续若开展文献物理复现，应另行冻结多周期统计起点、周期数、网格/时间步敏感性和
Shiels 指标；本轮不自动延长、不启动三切片、不进入长时间 VIV。
