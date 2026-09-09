# 历史 CFD 验证—当前生产基线同一性及最小补充方案

**任务**：`CFD_ANCF_VIV` 硕士课题主线只读工况盘点

**日期**：2026-09-09

**范围**：固定圆柱、有效规定运动 run4、正式三切片生产 CFD 之间的证据同一性。

**运行边界**：本轮没有启动 OpenFOAM、ANCF、preCICE 或任何新耦合算例；没有修改生产源码、网格、物理参数、adapter、回滚实现或历史 runtime。

## 1. 结论摘要

1. 当前正式三切片使用的 expanded-medium `polyMesh` 与有效规定运动 run4 的 `interpolatingSolidBody` 算例逐文件一致，而不是仅有相同单元数。当前 runtime 的 `points/faces/owner/neighbour/boundary/cellZones/faceZones/pointZones` SHA256 均与 run4 A/D=0.1 相同；`nPoints=16524`、`nCells=16244`、`nFaces=56994`、`nInternalFaces=24226` 也一致。
2. 当前生产的物理常数、层流模型和 `fvSchemes` 与 run4/precursor 一致；但它不是 run4 的数值复制：当前从 `PRECURSOR_STATE_V1` 的 `t=0.1 s` 已发展流场启动，`deltaT=0.005 s`，使用 `displacementLaplacian + preCICE/pointDisplacement`，而 run4 为 `t=0`、`deltaT=0.0025 s`、原生 `interpolatingSolidBody`。当前 `fvSolution` 还增加了 `cellDisplacement` 求解器条目，三个 `fvSolution` 文件不相同。
3. 固定圆柱 Gmsh `full30b` 研究已经证明 Re=100 圆柱的网格/时间步敏感性和脱涡趋势，但 small-domain 与 expanded production 的阻塞率不同；expanded-medium 的历史 Cd/St 摘要可复用作趋势和数量级证据，不能当作当前 `t=0.1` precursor + `dt=0.005` + 动网格路径的逐项验证。
4. 有效 run4 已证明 expanded-medium 上原生 `interpolatingSolidBody` 在 A/D=0.1、0.3、0.5 的规定运动可完成，并提供了力、相位、功率和网格质量摘要；它不能直接证明当前 `displacementLaplacian`/preCICE 输入路径的力响应等价。run3 因缺失 `FoamFile` 头而实际静止网格，明确排除。
5. 因此暂不需要重建网格或重新设计统一 CFD 基线。真正的最小缺口是：用当前生产数值设置做一次无结构固定/零运动基线，再做一次同一 expanded-medium、同一初始场和同一时间离散下的规定运动桥接。两项都属于未来候选实验，本轮只规划、不执行。

历史状态保持不变：正式三切片 0.05 s 仍为 `FAIL_CLOSED`，最后共同有效提交为 OF `0.145 s`，W10 未提交；W10 跨通道力重放的严格预声明容差 gate 仍为 `NOT_EVALUABLE`。`Persistent U/Uf oldTime` 指纹缺口保持独立资格项，不能被写成当前力放大的根因。

## 2. 证据索引与可复用性

| 证据 | 实际路径 | 当前可见内容 | 适用性 |
|---|---|---|---|
| 固定圆柱 full30b | [`cases/openfoam/fixed_cylinder_study_full30b`](../../cases/openfoam/fixed_cylinder_study_full30b) | coarse/medium/fine、两档 dt 的 case 字典、Gmsh 转换和 OpenFOAM 原始日志 | 可复核工况和日志；`results/03_fixed_cylinder/sensitivity_full30b` 及 postProcessing 汇总当前缺失 |
| 固定圆柱汇总 | [`docs/03_fixed_cylinder_verification.md`](../03_fixed_cylinder_verification.md) | 4 组 Gmsh full30b Cd、Cl 半峰值、St、CFL；15–30 s 统计窗口 | 报告级历史结果，不等于当前生产配置的原始时程 |
| 扩大域/规定运动汇总 | [`docs/03_prescribed_motion_quantitative_addendum.md`](../03_prescribed_motion_quantitative_addendum.md) | expanded 16244-cell 静止/规定运动结果、pimpleFoam A=0 对齐、时间/网格补查 | 可作为历史趋势和差异量化；结果目录在当前工作树缺失 |
| 有效规定运动 run4 | [`cases/openfoam/prescribed_motion_extended/prepared_dynamic_mesh_comparison_run4`](../../cases/openfoam/prescribed_motion_extended/prepared_dynamic_mesh_comparison_run4) | 六个 run4 case 的字典、网格、原始 `log.pimpleFoam`；interpolating 三个振幅完成 | 可复核输入和完成状态；`results/03_dynamic_mesh_comparison/run4` 的 CSV/JSON 摘要缺失 |
| 动网格选型 | [`docs/03_dynamic_mesh_selection.md`](../03_dynamic_mesh_selection.md) | run3 排除原因、run4 指标、solidBody 失败范围 | 对方法筛选有效，不是当前 preCICE 路径的等价性证明 |
| 当前正式 runtime | [`runtime/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001`](../../runtime/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001) | 三片实际 case、字典、owner/adapter manifest、ABI closure、原始耦合 trace | 当前生产身份和失败轨迹的权威证据；immutable |
| precursor | [`results/fixed_cylinder_precursor_initialization_contract_v1_run_002/PRECURSOR_STATE_V1`](../../results/fixed_cylinder_precursor_initialization_contract_v1_run_002/PRECURSOR_STATE_V1) | `t=0.1 s` 的 U/p/phi 指纹和 mesh 来源 | 当前生产初始场来源；只证明 startup-balanced 合同，不证明长统计稳态 |
| ANCF 阶段一 | [`docs/02_ancf_phase1_report.md`](../02_ancf_phase1_report.md) | MATLAB 结构实现、虚功/Hᵀ、Newmark、checkpoint/restart、网格/时间敏感性 | 结构软件和接口证据；不是公开物理基准 |
| ANCF C++ modal/free | [`docs/solver_validation_v3/PHASE2_ANCF_MODAL_AND_FREE_VIBRATION.md`](../solver_validation_v3/PHASE2_ANCF_MODAL_AND_FREE_VIBRATION.md) | C++ 静力、模态和零流体自由振动诊断 | MATLAB/C++ 模态数值对照仍 `reference_not_available` |
| ANCF force scale | [`docs/solver_validation_v3/PHASE1_FORCE_SCALE_AUDIT.md`](../solver_validation_v3/PHASE1_FORCE_SCALE_AUDIT.md) | Hᵀ 映射恒等式和物理力尺度缺口 | 说明单位/span/切片长度合同，不能替代公开物理验证 |

缺失项已按证据边界处理：没有重新生成历史 CSV/JSON，也没有把报告表格倒推成“原始结果文件存在”。

## 3. 三组 CFD 工况同一性矩阵

状态标记：**一致** = 文件或源码可逐项确认；**不同** = 已找到实际差异；**不足** = 当前没有足够原始证据。

| 维度 | 固定圆柱 full30b | 有效规定运动 run4 | 当前三切片生产 CFD |
|---|---|---|---|
| 几何/域 | small Gmsh：约 `x/D=[-5,10]`、`y/D=[-5,5]`；expanded 结果另有 `[-10,20]×[-15,15]` | expanded：`[-10,20]×[-15,15]`、3.33% 横向阻塞 | expanded；与 run4 `interpolatingSolidBody_A0p10` 的 polyMesh 文件逐个 SHA 一致 |
| 网格 | full30b：1772/3268/8360 cells（coarse/medium/fine） | medium expanded：16244 cells | 16244 cells；owner header `16524/16244/56994/24226`，与 run4 一致 |
| polyMesh 身份 | 不同于 expanded medium 的 small study；expanded 结果的目录摘要缺失 | `points` `FBDBB5…9012F`、`faces` `68C0FB…693C`、`owner` `1CF775…0AED`、`neighbour` `D331ED…45CF` 等七个文件 | 七个对应文件逐个相同；不是“checkMesh 相近”推断 |
| 流体物性 | `D=1 m, U=1 m/s, rho=1000, nu=0.01, Re=100` | 同左 | `physicalProperties` SHA=`0d3de074…3186`，与 run4/precursor 相同；laminar |
| 初始场 | 从 `t=0` 启动，含 `setFields` 的 `Uy=0.1` 局部触发种子 | 从 `t=0` 启动；原始均匀流场 | 从 `PRECURSOR_STATE_V1` 的 `t=0.1 s` 发展流场启动；U/p/phi 指纹与 precursor 相同 |
| 时间 | full30b `dt=0.0025/0.00125`，统计 15–30 s | `dt=0.0025`，20 s；统计 5–20 s，phase/power 取完整周期 | `dt=0.005`，OF `0.100→0.150 s`；10 个短窗口，非统计稳态算例 |
| 求解器 | `icoFoam`，Euler | `pimpleFoam`，Euler，`linearUpwind` | `pimpleFoam`，Euler，`linearUpwind`；当前运行增加 adapter、动态网格字段和恢复逻辑 |
| fvSolution | full30b 的 icoFoam/PISO 配置 | pimpleFoam：GAMG/PBiCGStab，outer=1、correctors=2 | 主要线性求解设置相同，但新增 `cellDisplacement`/`cellDisplacementFinal`；文件 SHA 与 run4 不同 |
| 运动/网格路径 | 静止 | OF10 原生 `interpolatingSolidBody`，`innerDistance=.75`、`outerDistance=2.5`，正弦 `y=A sin(ωt)` | `displacementLaplacian`，`pointDisplacement/cellDisplacement`，位移由 preCICE/ANCF 输入；没有原生 sinusoidal mover |
| 动网格质量 | 静止网格质量按各 study 日志 | run4 interpolating：determinant `0.52991`，最小体积 `1.5911e-3 m³`；三振幅完成 | 正式 runtime 三片 checkMesh 通过；0.05 s 运行 Co/containment 仍失败，checkMesh 不等于力可信 |
| 力定义 | `forces/forceCoeffs`，`rhoInf=1000`、`lRef=Aref=1`，单位展向 | 同一参考定义；历史摘要含 Cd、Cl、相位、功率 | `cylinderForces` 仍为 cylinder、`rhoInf=1000`；adapter 另负责 Force 传输和切片映射，需单独保持 N 与单位展向合同 |
| 预处理/时间历史 | 有启动瞬态后 15–30 s 统计 | 5–20 s 统计、2 周期相位/功率窗 | `PRECURSOR_STATE_V1` 只提供 `t=.1` 场指纹；U/Uf oldTime 缺口仍独立记录 |

### 3.1 可确认的文件级一致性

当前 formal runtime 与 run4 A/D=0.1 的 `constant/polyMesh` 七个文件逐个一致；与 precursor 的 polyMesh 也一致。当前 formal、run4、precursor 的 `fvSchemes` SHA 均为 `8dde725a…c4f26`；`physicalProperties` 均为 `0d3de074…3186`；`momentumTransport` 均为 `6a59c07e…0b192`。这足以确认几何、物性和主要离散字典的共同来源。

不能因此说三者是同一算例：`controlDict`、`fvSolution`、初始场、时间步和运动/事务层明确不同。尤其当前 production 的动态路径与 run4 的 native mover 不是同一实现。

### 3.2 当前生产二进制身份

来自 immutable `adapter_manifest.json`：

- adapter：`c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17`；
- Foundation 10 isolated ABI：`linux64GccDPInt32Opt`，preCICE 3.4.1；
- `pimpleFoam` SHA：`c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43`；
- `libOpenFOAM.so` SHA：`a34df8ad17f8250071c697d150e593563f2152c194b87fdb906b7a6493f37cde`；
- `libfiniteVolume.so` SHA：`5a820734c0a61a8bd6cdb730d95a651e002848d9d9d4d8a4897ea42608a2e48e`；
- `libfvMotionSolvers.so` SHA：`debc2c86635805c616874612c9c361477424ec58cba77ccc46853b786750eb30`；
- `libfvMeshMovers.so` SHA：`da199da31b42a7b5e07248864cb91c6556dba0afa4db74507879f4124d307e78`；
- ABI closure：manifest 标为 `PASS`，运行时主 OF 库均来自 isolated `owner_diagnostic_abi_build_001`，不是 `/opt/openfoam10`；完整 `ldd -r` 保留在 runtime。

## 4. 历史固定圆柱能证明什么

`fixed_cylinder_study_full30b` 的报告级敏感性结果如下，统计窗均为 `15–30 s`：

| 网格/dt | cells | Cd mean | Cl 半峰值 | St | max CFL |
|---|---:|---:|---:|---:|---:|
| coarse/0.0025 | 1772 | 1.37864 | 0.15410 | 0.13903 | 0.10031 |
| medium/0.0025 | 3268 | 1.40753 | 0.28274 | 0.15009 | 0.15979 |
| fine/0.0025 | 8360 | 1.41865 | 0.28850 | 0.17142 | 0.26224 |
| medium/0.00125 | 3268 | 1.40707 | 0.28215 | 0.14981 | 0.07993 |

它证明：Re=100、单位展向、给定小域和离散设置下，交替脱涡可重复，medium 的两档时间步结果接近，网格差异对 Cd、Cl、St 不可忽略。它不能证明当前 expanded 16244-cell、`pimpleFoam + linearUpwind`、`dt=.005`、发展流场和 displacementLaplacian 路径的精确力统计。

报告还记录 expanded-medium 静止结果 `Cd=1.29027`、`Cl` 半峰值 `0.24895`、`St=.15367`；相对 small-medium，Cd 和升力幅值分别变化约 8.33% 和 11.95%，说明阻塞率是当前基线的重要因素。expanded 摘要的原始 `results/` 目录当前缺失，因此这些数值必须标为历史报告级证据。

公开 Re=100 参考的共同趋势约为 `St=0.16–0.17`、平均 Cd 约 `1.33–1.40`；本项目已在固定圆柱报告中引用同一文献范围。文献几何和计算域并不自动等于本项目 expanded case，故这里只能作趋势/范围比较，不能把历史数字改写为精确参考值。

## 5. 有效规定运动 run4 能证明什么

run4 的输入是

```text
D=1 m, U=1 m/s, rho=1000 kg/m3, nu=.01 m2/s, Re=100
expanded medium, 16244 cells, dt=.0025 s, pimpleFoam, Euler
f=.16 Hz, omega=1.00530964914873 rad/s
y(t)=A sin(omega t), A/D = .1, .3, .5
```

有效方法是原生 `interpolatingSolidBody`；run4 文档给出的完成结果为：

| A/D | 完成 | Cd mean | Cl 半峰值 | 相位 vs y | 平均功率 |
|---:|---|---:|---:|---:|---:|
| 0.1 | 是 | 1.43139 | 0.53076 | 62.12° | 10.830 W |
| 0.3 | 是 | 1.69385 | 0.50012 | 82.31° | 27.071 W |
| 0.5 | 是 | 1.88601 | 0.18832 | −35.89° | −3.363 W |

这些结果适合复用为：expanded 网格在已知正弦位移下的网格运动筛选、力/位移相位和功率处理示例，以及高振幅非线性的警示。它们不适合直接复用为当前 preCICE + `pointDisplacement` + `displacementLaplacian` 路径的定量基线，因为运动实现、dt、初始场和力传输合同不同。

run3 六组力时程相同，根因是动态字典缺失 `FoamFile` 头，OpenFOAM 按静止网格路径运行；run3 只保留为配置审计失败证据，不能作为规定运动结果。run4 的 `results/03_dynamic_mesh_comparison/run4` 摘要文件和后处理目录目前缺失，不能把文档表格包装成现存原始 CSV。

## 6. ANCF 独立验证现状

| 层级 | 已有证据 | 能证明 | 仍缺什么 |
|---|---|---|---|
| MATLAB ANCF 阶段一 | 刚体/轴向/质量、虚功、解析切线、网格/时间步、checkpoint/restart | 结构公式、数值实现、Hᵀ 载荷接口和重启可复现 | 公开物理试验/解析 VIV 基准；传统梁对照 |
| C++ modal/free | 静力平衡、质量归一化模态、零流体 20 s 自由振动 | C++ 内核在受控零流体条件下可运行；阻尼明确为零 | MATLAB/C++ 模态数值对照仍不可用；没有流体物理参考 |
| Force scale | `Hᵀ` 恒等式与 CSV 合同测试 | 映射数学一致性 | 历史 Stage382 缺 `unit_span_m`、tributary length 和 raw OpenFOAM integrated force，物理量纲仍不可单独闭合 |
| 三切片耦合 | 两窗口和 W10 replay 等软件/事务证据 | 回滚、跨通道数值一致性和故障轨迹 | 自由 VIV 物理可信度；0.05 s 已 FAIL_CLOSED |

ANCF 结果不能因为 MATLAB/C++ 内部一致就称为物理验证；下一项真正缺口是带明确质量、刚度、阻尼、单位跨度、边界和公开参考量的独立结构或单切片基准，而不是重做已完成的公式单元测试。

## 7. 是否需要重建统一 CFD 基线

**决定：暂不重建网格统一基线；需要一条最小的当前配置桥接链。**

理由：

- 几何来源已经闭合：当前 production、run4 expanded-medium 和 precursor polyMesh 逐文件一致；
- 物性、层流模型和主要 `fvSchemes` 已闭合；
- 历史固定/规定运动已经提供了 Re=100 的统计和动网格筛选证据；
- 差异主要集中在当前生产的时间步、初始发展流场、`fvSolution` 动网格条目、位移输入路径和 preCICE/adapter 事务层，不是“需要再造一个网格”。

因此不建议现在把 small-domain full30b、expanded run4 和三切片生产 case 强行合并成一个数值结果表，也不建议为了取得表面一致而改动生产字典。

## 8. 最小可执行验证方案（只规划，不执行）

### A. 当前生产配置的固定/零运动 CFD

| 项目 | 规划 |
|---|---|
| 科学目的 | 区分当前 `pimpleFoam + linearUpwind + dt=.005 + precursor` 数值设置与历史固定圆柱结果的差异，检查无运动时是否仍有合理 Cd/St/Co |
| 唯一改变因素 | 取消结构运动/耦合输入；保留当前 expanded mesh、物性、`fvSchemes`、`fvSolution`、dt 和 forces 定义 |
| 输入 | `PRECURSOR_STATE_V1` 的 U/p/phi at `t=.1`；若要统计 St，必须继续到足够的稳态窗口，不得用 0.05 s 数据代替统计 |
| 最小运行量 | 一个当前配置 case；短时 smoke 只用于连续性，论文级 Cd/St 必须另设启动剔除和不少于 10 个完整脱涡周期的统计窗。步数按 `N=(t_end-.1)/.005` 预先冻结，不在运行中延长 |
| 指标 | `Cd_mean`、`Cl` RMS/谐波幅值、St、Co、PIMPLE 残差、force history、mesh quality |
| 停止条件 | FPE、负体积、非有限力、统计窗不足、Co 越界或结果未达到预先冻结的周期一致性 |
| 判别 | 若 Cd/St 可复现而升力仍偏离，优先归因于对流格式/域/启动差异；若所有量均偏离，需检查初始场/时间层/力定义，不先归因于耦合不稳定 |

### B. 同一基线的规定运动桥接

| 项目 | 规划 |
|---|---|
| 科学目的 | 把“已验证的 native interpolatingSolidBody”与“当前 pointDisplacement + displacementLaplacian 输入路径”分开比较 |
| 唯一改变因素 | 同一 expanded mesh、物性、初始场、fvSchemes/fvSolution、dt 和力定义；仅改变运动驱动实现，先用 `A/D=.1, f=.16 Hz` 正弦输入 |
| 输入 | 完整 `y(t)`、`v(t)` 和时间层；不只比较圆柱质心。所有 boundary displacement、网格速度/通量和实际 cylinder points 必须记录 |
| 最小运行量 | 一个 A/D=.1 受控桥接 case，统计至少 10 个完整强迫周期；若要检查幅值非线性，再单独规划 A/D=.3/.5，不在同一实验中扩展 |
| 指标 | 实际点位移与输入、mesh velocity/meshPhi、压力/黏性/总力、Cd/Cl、力—位移与力—速度相位、平均功率、Co、determinant、体积、非正交性 |
| 停止条件 | 输入时间层错位、点位移不一致、网格通量非有限、负体积、力映射单位不闭合或周期统计不稳定 |
| 判别 | native 与 displacementLaplacian 结果一致则支持运动路径等价；只在 Co/mesh quality 不同而力相近时，才把差异限制为网格运动离散问题；不同力响应需先检查时间/初始场/边界运动，再研究物理反馈 |

### C. 独立单切片自由 FSI（后续，不属于本轮）

选一个公开或可核查的二维质量—弹簧—阻尼圆柱基准，冻结 `m`（单位展向）、`k`、`c`、边界、Re、D、U、流体力定义和参考响应。结构自然频率、质量比和约化速度必须由这些量显式计算，不能把 50 m 立管总质量/刚度任意压缩成一个二维振子。先使用 A/B 的 CFD 力合同，再做短时单切片自由响应；它的结论范围是该明确物理模型，不能外推为三切片柔性立管验证。

## 9. 可保留成果与未闭合项

**可直接保留**：expanded-medium 文件级网格来源；full30b 的网格/时间敏感性方法；run4 `interpolatingSolidBody` 的规定运动筛选；precursor 的 U/p/phi 起点合同；ANCF 软件实现、虚功和 checkpoint/restart 证据；W10 完整 predictor 与跨通道数值一致性（严格容差标签仍不改）。

**不能直接升级**：历史报告数值为当前 production 的精确 Cd/St 参考；run4 为当前 preCICE 位移路径验证；formal 0.05 s 的短时 force 峰为物理 VIV 结论；terminal PIMPLE/checkMesh 通过为力可信结论；MATLAB/C++ 一致为公开物理验证。

**独立资格项**：`Persistent U/Uf oldTime` 数值指纹缺口继续保留，不能作为本轮放大根因。

## 10. 人工选择建议

优先顺序建议为：

1. A：当前生产 CFD 配置固定/零运动基线；
2. B：同一基线的规定运动桥接；
3. ANCF 缺失的公开/解析基础验证；
4. C：有明确物理参数的单切片自由 FSI；
5. 在上述结果可解释后，才重新评估三切片连续耦合。

本轮不授权也不执行 A/B/C 中任何算例。

```text
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

### 参考资料

- 项目固定圆柱与动网格报告：见本报告第 2 节链接。
- 公开 Re=100 圆柱参考：Fu et al., 2015, <https://onlinelibrary.wiley.com/doi/10.1155/2015/568176>；项目原报告同时列出 Jiang & Cheng 2017，<https://doi.org/10.1017/jfm.2017.685>。这些文献只用于趋势/范围比较，不能替代当前配置的独立桥接。
