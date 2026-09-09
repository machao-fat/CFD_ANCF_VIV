# Shiels S5-K9.88 独立单切片自由 FSI 首次有限接入 V2

## 结论

`SHIELS_S5_K9P88_SINGLE_SLICE_FREE_FSI_FIRST_TRIAL_V2 = PASS_FOR_BOUNDED_FIRST_TRIAL`。

这是一次真实 preCICE--OpenFOAM--Python `SDOFRunner` 的双向、parallel-implicit
自由反馈接入验证。它从合法的 OF `0.105 s` 动态零运动重启状态出发，以
`dt=0.005 s` 完成至 `0.155 s` 的 10 个接受窗口。每个窗口均为 3 次耦合迭代；
共记录 30 次试算和 20 次结构 checkpoint restore。所有预声明硬门均通过。

本结论只覆盖当前 Python SDOF 包装层、当前 OF10 owner-diagnostic ABI 和该 0.05 s
有限窗口。它不验证 C++ ANCF、50 m 立管、锁定、稳态 VIV、网格/时间步收敛或长期稳定性。

## V1 失败记录与本次独立运行

原始
[V1 报告](SHIELS_S5_K988_SINGLE_SLICE_FREE_FSI_FIRST_TRIAL_V1_REPORT.md)及
`runtime/shiels_s5_k988_single_slice_free_fsi_first_trial_v1_run_001` 保持
`FAIL_CLOSED`：当时 Bash 在启动任何 participant 或 CFD 前因 `PYTHONPATH` 尾部孤立
单引号退出。

用户随后单独授权了唯一的格式修复和一次新的独立尝试。唯一生产前改动是 launcher
将两个 `PYTHONPATH` 路径置于同一对引号内；没有改动 SDOF 算法、Adapter、OF10-owned
restore、网格、物性、`dt`、PIMPLE、preCICE 收敛设置或力映射。审计器另修正为按物理
时间层选取 `cylinderForces` 的最后一条记录，并保留每时间层的原始记录数；这不会改变
任何数值输出，也未触发第二次求解。

本次 immutable runtime 为
`runtime/shiels_s5_k988_single_slice_free_fsi_first_trial_v1_run_002`，离线审计结果为
`results/shiels_s5_k988_single_slice_free_fsi_first_trial_v1_run_002/first_trial_result.json`。

## 冻结物理、初态与二进制身份

| 项目 | 值 |
|---|---:|
| Shiels 工况 | `Re=100, m*=5, k*=9.88, b*=0` |
| `D, U, rho, nu, Lz` | `1 m, 1 m/s, 1000 kg/m3, 0.01 m2/s, 1 m` |
| `M, K, C` | `2500 kg, 4940 N/m, 0 N s/m` |
| 自由度与力 | 仅横向；`Fy=压力+黏性`的完整 1 m 展向总力 |
| 初态 | `y0=0, v0=0, a0=-0.0183863145749328 m/s2` |
| 初始流体力 | `Fy0=-45.965786437332 N`（压力 `-47.2938883278 N`，黏性 `+1.328101890468 N`） |
| 时间区间 | OF `0.105 -> 0.155 s`，10 个窗口，`dt=0.005 s` |
| 耦合 | parallel implicit，min/max `2/8`，无加速 |

初态来自 `PRECURSOR_STATE_V1` 的原生动态零运动重启；未使用人工相容 `Uf`
反事实场。`contract.json` 记录了 `U/p/phi/Uf`、位移场、`meshPhi`、points 和时间状态的
SHA256。实际 ABI 为独立 `owner_diagnostic_abi_build_001`：
`pimpleFoam` SHA256
`c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43`，Adapter SHA256
`c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17`；预检查确认
`ldd -r` 无未解析符号且未混入 `/opt/openfoam10`。

## 运行与硬门结果

| 门 | 结果 | 证据 |
|---|---|---|
| 两进程返回 | PASS | `structure=0 fluid=0` |
| 接受窗口 | PASS | 10/10，最后共同接受时间 `0.155 s` |
| 回滚 | PASS | 20 次 restore；30 次 trial |
| 迭代范围 | PASS | 每窗口 3 次，位于 `[2,8]` |
| 初始受力加速度 | PASS | 与 `Fy0/M` 相差不超过 `1e-15 m/s2` |
| 真实边界/网格运动 | PASS | 80 个 cylinder 顶点最大误差 `4.9755e-13 m`，小于 `1e-9 m` |
| 点位移场 | PASS | 非均匀场逐点误差不超过 `3.65e-18 m`；uniform 表示的两个时间层也由全部 80 顶点几何比较覆盖 |
| 流体--结构力身份 | PASS | 每窗口 `cylinderForces` 总 `Fy` 与 participant `Fy` 的最大差 `4.44e-12 N` |
| 结构 containment | PASS | 最终 `y=-2.4158839955e-6 m`，`v=-6.9885983075e-5 m/s`，`Fy=-2.6209403001 N` |
| 流体质量 | PASS | 最大 Co `0.35010195544 < 0.5`；最大全局连续性 `2.5360e-11 < 1e-8`；无 FPE/负体积 |
| 终态网格 | PASS | 标准 `checkMesh`: `Mesh OK` |

`cylinderForces` 的原始文件在多数中间时间层保留三条同时间记录（分别对应隐式 trial），
`0.155 s` 持久化一条最终记录。审计没有将 31 条 function-object 输出误当作 10 个物理
窗口，而是按时间层保留最后一条，并将原始计数写入结果 JSON：`.110` 至 `.150` 各 3 条，
`.155` 为 1 条。每个选定最终记录均与同一窗口的 participant 力直接求和一致。

## 能量与物理解释边界

无阻尼结构的终态机械能为 `6.119479431700128e-6 J`，累计流体做功为
`6.119479431700127e-6 J`，二者差为 `-9.26442286059391e-23 J`。这里机械能增长是流体
做功的结果，不适用自由衰减的“能量恒定”门。

运行仅覆盖约 `0.011` 个真空自然周期（`Tn≈4.46978 s`），因此不能与 Shiels 的稳态
`A/D=0.57`、`fD/U=0.198`、升阻力统计量作直接对比，也不能据此判断 lock-in 或 VIV
物理正确性。

## 资格状态与后续

```text
NEXT_SINGLE_SLICE_SDOF_FREE_DECAY = COMPLETED_PASS
NEXT_SINGLE_SLICE_FREE_FSI = BOUNDED_FIRST_TRIAL_PASS; NO_EXTENSION_AUTHORIZED
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

若未来需要研究 Shiels 的多周期响应，应先单独冻结统计起始时间、周期数、网格与时间步
敏感性、力/位移/频率/相位/能量评价指标及失败停止条件；本次不会自动延长或启动下一项。
