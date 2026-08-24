# 任务二补充审查：规定运动圆柱的定量可信度

日期：2026-08-04

结论：**条件通过**。固定圆柱扩大域、pimpleFoam 静止极限、10 个以上完整强迫周期、medium/fine 与 Euler/backward 补查，以及两类动网格适用范围均已建立证据链；但 A=0 的升力幅值仍有约 7% 的求解器/离散差异，规定运动不能单独证明自由系统锁定，也没有据此宣称整根柔性立管 VIV 已完成。

本审查不修改 `src/structure_ancf_matlab`，不修改已经通过的 CSV 合约和回放测试。新增的分析脚本只读取 OpenFOAM 力输出或已有载荷 CSV。

## 1. 统一物理和统计定义

所有圆柱算例采用 `D=1 m`、`U_inf=1 m/s`、`rho=1000 kg/m^3`、`nu=0.01 m^2/s`，因此

`Re = U_inf D / nu = 100`。

前后展向面为 `empty`，展向厚度为单位长度 `Lz=1 m`；入口为 `U=(1,0,0) m/s`，上下边界为 `symmetryPlane`，力积分参考面积为 `Aref=1 m^2`。二维力积分先解释为单位展向力 `f_2D [N/m]`；若代表结构切片长度为 `l_slice`，回传结构的力为

`F_slice = f_2D * l_slice`。

规定运动为

`y(t) = A sin(2*pi*f*t)`，`v_y(t) = 2*pi*f*A cos(2*pi*f*t)`。

功率采用 `P=F_y*v_y`。已知强迫频率下的相位由谐波最小二乘拟合、复解调和交叉谱三种方式交叉检查；周期统计总是按完整周期截取。`phase_vs_displacement` 以 `y(t)` 为零相位，`phase_vs_velocity` 以 `v_y(t)` 为零相位。

正式网格由 Gmsh 4.14.1 生成，默认可执行文件为 `D:\Gmsh\gmsh-4.14.1-Windows64\gmsh-4.14.1-Windows64\gmsh.exe`。OpenFOAM 环境和版本冻结见 [03_openfoam_environment.md](03_openfoam_environment.md)。

## 2. 扩大计算域检查

固定圆柱对比使用同一 Gmsh medium 近壁分辨率、`icoFoam`、`dt=0.0025 s` 和 30 s 完整计算。小域为 `x/D=[-5,10]`、`y/D=[-5,5]`，横向阻塞率按 `D/H` 约为 10%；扩大域为 `x/D=[-10,20]`、`y/D=[-15,15]`，上游 10D、下游 20D、上下边界 15D，横向阻塞率约为 3.33%。

| 域 | cells | `Cd_mean` | `Cl` 半峰峰值 | `St` | 最大 CFL | wall clock |
|---|---:|---:|---:|---:|---:|---:|
| 小域（已有基线） | 3,268 | 1.40753 | 0.28274 | 0.15009 | 0.15979 | 44 s |
| 扩大域 | 16,244 | 1.29027 | 0.24895 | 0.15367 | 0.17504 | 412 s |

上表的小域统计值来自既有 `fixed_cylinder_study_full30b/medium_dt0p0025`；两者近壁尺寸保持同一量级，扩大域增加的主要是远场单元。

扩大域相对于小域使平均阻力降低约 8.33%，升力半峰峰值降低约 11.95%，而 `St` 只改变约 2.38%。因此当前约 10% 阻塞率对阻力和升力幅值具有不可忽略影响，对脱涡频率的影响较小但不能假定为零。第三阶段自由耦合默认使用扩大域；不能为了节省计算时间继续把小域作为默认域。

扩大域静态 `checkMesh` 的代表质量为：最小体积 `1.5911e-3 m^3`、最大非正交性 `30.64 deg`、最大 skewness `0.5031`、最小 cell determinant `0.5299`。`checkMesh` 对二维挤出棱柱会额外报告非对齐挤出边，这是几何拓扑警告；本报告同时保留该警告，并单独核验正体积、非正交性、skewness 和 determinant。

## 3. pimpleFoam 的 A=0 静止极限

静止极限在既有小域 medium 网格上与 `icoFoam` 固定圆柱保持相同物理参数和 `dt`。`pimpleFoam` 的原始模板使用 `linearUpwind`，其结果不能直接作为与 `icoFoam` 的严格 solver-limit 对照，因此又建立了 `Gauss linear`、`nOuterCorrectors=1/2` 的对齐算例。

| 算例 | 对流格式 | outer | `Cd_mean` | `Cl` 半峰峰值 | `St` | 最大 CFL | wall clock |
|---|---|---:|---:|---:|---:|---:|---:|
| `icoFoam` 固定基线 | — | — | 1.40753 | 0.28274 | 0.15009 | 0.15979 | 44 s |
| `pimpleFoam A=0` 原始 | linearUpwind | 1 | 1.38058 | 0.22829 | 0.15077 | 0.16059 | 152 s |
| `pimpleFoam A=0` 对齐 | linear | 1 | 1.40659 | 0.26603 | 0.15117 | 0.15983 | 148 s |
| `pimpleFoam A=0` 对齐 | linear | 2 | 1.40560 | 0.26232 | 0.15015 | 0.15983 | 213 s |

采用对齐的 `Gauss linear` 后，`Cd` 与 `St` 已分别进入约 0.14% 和 0.04% 的差异范围；升力幅值仍比 `icoFoam` 低约 7.2%（outer=2），说明 A=0 极限是**条件一致**而不是逐项完全相同。原始 `linearUpwind` 与 `icoFoam` 的升力幅值差约 19%，因此不用于后续相位/能量基准。第三阶段至少保留这个 solver-limit 残差作为数值不确定性。

## 4. 延长规定运动：完整周期、相位和功率

正式标签不再使用 `non_locking/near_locking`，而使用 `below_shedding_forced` 和 `near_shedding_forced`。规定运动只能说明“给定运动输入下的流体响应”，不能单独证明自由系统锁定。

### 4.1 `near_shedding_forced`

参数为 `A/D=0.1`、`fD/U=0.16`、总时长 125 s；去除前 50 s 后统计 50--125 s 的 12 个完整周期。结果来自 `results/03_prescribed_motion_extended/near_shedding_forced_extended125/whole_cycle_analysis/summary.json`：

- FFT 主峰 `0.159995 Hz`，与输入频率一致；
- 已知强迫频率升力系数幅值 `Cy=0.279979`；
- 力—位移谐波相位 `130.811 deg`，复解调 `130.809 deg`，交叉谱 `130.644 deg`；
- 力—速度谐波相位 `40.811 deg`；
- 平均功率 `5.326 W`，统计窗流体输入功 `399.439 J`；
- 周期功标准差 `0.261 J`，周期幅值标准差 `0.000701`，周期相位标准差 `0.417 deg`；
- 相邻周期功和幅值的最大相对变化分别为 `0.892%` 和 `0.570%`。

这组数据满足“去除瞬态后至少 10 个完整周期”及稳态周期一致性要求，但仍是规定运动结果，不是自由 VIV 锁定证据。

### 4.2 `below_shedding_forced`

参数为 `A/D=0.1`、`fD/U=0.08`、总时长 150 s；去除前 25 s 后统计 25--150 s 的 10 个完整输入周期：

- 输入频率谐波 `Cy` 幅值 `0.043919`；
- 力—位移相位约 `-92.073 deg`；
- FFT 主峰 `0.167997 Hz`，接近自然固定圆柱脱涡频率而不是输入 `0.08 Hz`；
- 平均功率 `-0.552 W`，窗内功 `-68.952 J`；
- 周期功标准差 `3.676 J`，周期幅值标准差 `0.02326`，周期相位标准差 `15.11 deg`；
- 相邻周期功和幅值变化达到约 `40.1%` 和 `39.5%`。

因此该工况标记为非稳态/拍振型规定运动响应；它证明统计工具能够识别输入频率和自然脱涡频率不一致，不能被解释成稳定的“非锁定自由系统”或锁定边界。

## 5. near-shedding 空间/时间离散补查

补查矩阵为 expanded 域、原生 `interpolatingSolidBody`、`A/D=0.1`、`f=0.16 Hz`、`dt=0.0025 s`、总时长 82.5 s。统计窗为 18.75--81.25 s 的 10 个完整周期。结果文件在 `results/03_prescribed_motion_extended/discretization_run2/`；表格由 `phase_comparison_summary.csv` 自动生成。

| 算例 | cells | 时间格式 | `Cd_mean` | `Cl` 谐波幅值 | 力—位移相位 | 平均功率 | 最大 CFL | wall clock |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| medium Euler | 16,244 | Euler | 1.45847 | 0.30749 | 122.933 deg | 6.486 W | 0.17132 | 1,604 s |
| medium backward | 16,244 | backward | 1.45862 | 0.30498 | 124.352 deg | 6.328 W | 0.17103 | 1,642 s |
| fine Euler | 39,328 | Euler | 1.44994 | 0.29193 | 125.546 deg | 5.970 W | 0.26122 | 3,734 s |

medium Euler 与 backward 的 `Cd` 差约 0.010%，升力谐波幅值差约 0.82%，相位差约 1.42 deg，平均功率差约 2.44%，最大 CFL 差约 0.17%，计算成本增加约 2.4%。medium Euler 与 fine Euler 的 `Cd` 差约 0.59%，升力谐波幅值差约 5.06%，相位差约 2.61 deg，平均功率差约 7.96%；fine 的最大 CFL 为 0.26122、wall clock 为 3,734 s，分别约为 medium 的 1.52 倍和 2.33 倍。fine 网格结果仍保持正 determinant 和正体积，但代价显著增加。因此第三阶段采用 medium + backward 作为默认推进组合，并对关键工况保留 fine 复核，不把 medium 结果包装成网格无关结果。

## 6. 审查结论和第三阶段边界

| 验收项 | 判断 |
|---|---|
| 大域结果明确阻塞误差 | 通过；小域对 `Cd` 和升力幅值影响约 8--12% |
| pimpleFoam A=0 与固定基准一致 | 条件通过；`Cd/St` 很接近，升力幅值保留约 7% 残差 |
| 至少 10 个稳态强迫周期 | `near_shedding_forced` 通过 12 周期；below 工况被标记为非稳态 |
| medium/fine 与 Euler/backward 量化 | 通过；三组 82.5 s 算例均正常结束，均取 10 个完整周期 |
| 动网格方法适用范围 | 通过；见 [03_dynamic_mesh_selection.md](03_dynamic_mesh_selection.md) |

综合判断为**条件通过**：第三阶段默认采用扩大域、原生 `interpolatingSolidBody`、`backward` 时间格式，并保留 solver-limit 和网格敏感性误差；继续沿用“规定运动接口可信”这一结论，不宣称自由 VIV 或整根柔性立管 VIV 已验证。
