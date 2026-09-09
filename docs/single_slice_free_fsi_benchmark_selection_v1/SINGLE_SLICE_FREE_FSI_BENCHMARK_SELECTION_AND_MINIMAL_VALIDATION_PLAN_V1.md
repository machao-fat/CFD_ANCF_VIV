# 独立单切片自由 FSI：基准选择与最小验证计划 V1

## 结论与边界

本文件只冻结研究设计；没有启动 OpenFOAM、ANCF、preCICE 或耦合计算，也没有修改生产源码、物理参数、Adapter、OF10-owned restore 或历史 runtime。

建议将“二维、横向单自由度弹性支撑圆柱、Re=100”作为独立的物理基准族，而不是把 50 m 三切片立管等效压缩为一个振子。第一项未来计算应是**结构独立自由衰减**，随后才是同一几何与物性的固定圆柱，最后才是无 ANCF 的单自由度自由 FSI。只有在该 SDOF 物理链条通过后，才评估将它映射到一个受约束的 ANCF 模型；SDOF 通过不自动等同于 ANCF 物理验证。

当前不能把任一已有三切片或短时规定运动结果称为自由 FSI/VIV 验证。

## 已有证据链：可复用范围

| 证据 | 可复用结论 | 不能推出的结论 |
|---|---|---|
| 历史 Re=100 固定圆柱及 full30b | 已有固定流动、网格/时间步敏感性和脱涡研究可作索引；必须按实际 case 与统计窗口复核后才可作基线数据 | 不是当前动态/耦合路径的逐文件数值参考 |
| `PRECURSOR_STATE_V1` | 当前生产尺度为 `D=1 m, U=1 m/s, rho=1000 kg/m3, nu=0.01 m2/s, Re=100`；固定 precursor 已提供合法动态重启起点 | 0.1 s/0.105 s 的短输出不是稳定 St、Cd 或自由响应统计 |
| 零运动 Uf/phi 反事实 | 初始 `Uf` 重建与通量投影解释了固定/动态首步力差的主要部分 | 不解释三切片自由反馈放大，也不证明 OF10 缺陷 |
| V2 非零规定运动桥接 | 100 个输出时间层正确；完整圆柱边界运动满足 `1e-9 m`；Fx/Fy 相对 L2 为 `2.589866e-4/1.163411e-3` | 不是多周期 VIV、自由 FSI、附加质量或长期稳定性证明 |
| 三切片力合同 | 已有 N ↔ N/m ↔ 积分 N 与虚功一致性证据；历史 V2 最大映射误差 `1.46e-11 N`、归一化虚功误差 `8.51e-16` | 不应把已闭合的力身份问题重新假定为单切片首要嫌疑 |
| ANCF 独立/工程证据 | 早期 MATLAB/ANCF 静力、模态和短动态检查，以及 C++ transport/self-test 可作工程实现证据 | 当前生产 C++ 的严格独立数值资格仍有未闭合记录；不能以同源 MATLAB/C++ 一致冒充物理实验验证 |

保留而不改写的边界：正式三切片 0.05 s 仍 `FAIL_CLOSED`，最后共同有效提交为 OF 0.145 s；W10 力重放、回滚和映射证据不在本轮重新审计。

### V2 `pointDisplacement` 复核

V2 原始 `0.110/pointDisplacement` 的 `cylinder` patch 为
`nonuniform List<vector>`，实际写出 80 个 vector，而不是 `uniform` 单值表示。V2 结果的 `value_count=80` 与 80 个唯一圆柱边界顶点的几何比较一致。因此不存在“仅比较一个 uniform 值却宣称 80 点通过”的问题，无需改写 V2 报告或重跑。

## 文献候选与可比性

| 候选 | 已证实的公开信息 | 优点 | 当前缺口/处理 | 决定 |
|---|---|---|---|---|
| Placzek, Sigrist & Hamdouni, *Computers & Fluids* 38 (2009), DOI `10.1016/j.compfluid.2008.01.007` | 2D、Re=100、仅横向自由圆柱；无阻尼；`m y¨+k y=F_y`；报告 `A/D≈0.58` 于 `k_eff=2.32`，并给出力、相位、频谱和 2S 尾流 | 与目标 SDOF 最匹配，且同时覆盖 forced/free motion；明确指出 `H/D=20`、`L2/D=20` 的局限 | 原文以 `k_eff` 曲线呈现，当前尚未取得可审计的完整数值表和每个运行的独立 `m,k` 元组；不能把图形读数伪装成精确时程 | **首选文献锚点**；执行前取得原始 PDF/补充数据并版本化数字化表 |
| Tang et al., *Advances in Mechanical Engineering* (2013), DOI `10.1155/2013/890423` | Re=100；`m*=10`、`zeta=0.01`、`U_r=3.0–10.2`；明确给出每单位跨度的 `m,c,k` 方程、边界、域（上游 60D、下游 85D、半高 45D）及 Re=100 固定圆柱对照 | 输入参数和无量纲定义最完整；其 `U_r=5.2` 网格表给出 `Y_RMS=0.353` | 原始自由运动为 2DOF；不能作为横向 SDOF 的严格响应金标 | **参数与方程交叉核对**，不作为 SDOF 通过阈值 |
| Prasanth & Mittal, *JFM* 594 (2008), DOI `10.1017/S0022112007009202`；以及 Placzek 对 Shiels–Leonard–Roshko Re=100 结果的复现 | Re=100、低 Re 圆柱自由 VIV、`m*=10`/频率与固定圆柱脱涡关系；Shiels 极限参数结果给出 `A/D=0.47, fD/U=0.156` | 可用于 Re=100 响应机理、锁定和附加质量敏感性对照 | Prasanth/Mittal 的所选运动自由度和部分阻尼/域细节需在原始全文中逐项冻结；Shiels 的极限零质量/零刚度/零阻尼不适合自由衰减检验 | **候选机理对照**，不冻结为第一算例 |

因此，文献上最接近的选择是 Placzek 等的横向 SDOF Re=100 族；但在获取可审计原始资料前，不把其图形曲线改写为未经证实的精确数值门槛。

## 推荐的可执行基准合同（待人工批准后冻结）

为使结构独立试验、CFD 和耦合共享同一量纲，推荐采用当前生产 CFD 的物理尺度，而不是立管尺度；其为**项目定义的 SDOF 诊断基准**。发布时需与上表 Placzek 曲线进行形态比较，并将 Tang 的参数只作为交叉核对。

| 项 | 冻结值/定义 |
|---|---|
| 几何与流体 | `D=1 m`，二维单位展向 `L=1 m`；`rho=1000 kg/m3`，`nu=0.01 m2/s`，`U=1 m/s`，层流不可压；`Re=UD/nu=100` |
| 自由度 | 仅横向 `y`；流向、转动、轴向与 ANCF 其他自由度均不在该物理基准内 |
| 结构质量定义 | 干结构/振子线质量 `m'`；不预先加入流体附加质量，避免与 CFD 压力/黏性力重复计入 |
| 质量比 | `m*=m'/(rho*pi*D^2/4)=10`，故 `m'=7853.981633974 kg/m` |
| 频率与阻尼 | 选择 Tang 参数族中的 `U_r=5.2`、`zeta=0.01`；`f_n=U/(U_r D)=0.1923076923 Hz`、`omega_n=1.2083048668 rad/s` |
| 刚度与阻尼 | `k'=m' omega_n^2=11466.818298927 N/m2`，`c'=2 zeta m' omega_n=189.800084636 N s/m2` |
| 结构方程 | `m' y¨ + c' y˙ + k' y = F_y'`；`F_y'=F_y/L`，单位 `N/m`。当前 1 m CFD 展向的总 `F_y` 仅在明确除以 `L=1 m` 后作为该输入 |
| 系数 | `C_L=F_y'/(0.5 rho U^2 D)`；`C_D=F_x'/(0.5 rho U^2 D)`；`A*=A_y/D`；`U_r=U/(f_nD)`；`St=f_sD/U` |
| 初值 | `y(0)=0`、`y_dot(0)=0`；固定 CFD 必须从合法、单独记录的流场起点开始；不可复用三切片 rejected/tentative 状态 |
| 域与网格 | 在执行时从单一冻结 case 产生，至少报告上/下游、横向距离、阻塞比、近壁和尾流分辨率、polyMesh SHA；不假称当前 16244-cell expanded-medium 就已等价于文献域 |

`k'` 和 `c'` 是每单位跨度的刚度与阻尼，故单位分别为 `N/m2` 和 `N s/m2`。若以后采用总力而非线力，必须同时乘以同一实际展向长度，不能混用 N 与 N/m。

## 最小验证流程与停止条件

### 1. SDOF 结构独立自由衰减（第一项申请运行）

实现一个独立、可解析核对的 SDOF 参考积分器；它不替代 ANCF。解析目标为

`y(t)=y0 exp(-zeta omega_n t) cos(omega_d t + phi)`，
`omega_d=omega_n sqrt(1-zeta^2)`。

比较 `f_d`、包络衰减率、机械能和无载荷动量。拟议范围为 10 个真空周期
`10/f_n=52 s`；若延用 `dt=0.005 s`，为 10,400 步。停止条件：非有限值、能量在无载荷阻尼系统中非物理增长、或频率/衰减与解析式不一致。该阶段必须先通过，才讨论把同一 `m',c',k'` 表示为受约束 ANCF 的广义质量、刚度和阻尼。

### 2. 固定圆柱 CFD 基线

先只读核对历史 full30b 是否具有同一 `D,U,nu`、域、网格、`dt` 和统计窗口；不满足则不复用其 Cd/Cl/St 作为本 case 数值金标。若需补算，最小主算例应丢弃启动段，并保留至少 10 个固定圆柱脱涡周期的统计段；以 `St≈0.165` 估算，单周期约 `6.06 s`。例如总 `60 s`、`dt=.005 s` 为 12,000 步，不含之后单独批准的网格/时间步敏感性算例。

指标：平均 `C_D`、`C_L,rms`、`St`、时均流量/连续性、Co、残差、网格质量和统计窗敏感性。短桥接的 0.5 s 数据不得替代这些统计。

### 3. 单自由度自由 FSI

只使用步骤 1 的 SDOF 参考结构与步骤 2 同一 CFD case。比较稳态/准稳态的 `A*`、主频 `f/f_n` 和 `St`、`C_Dmean`、`C_Lrms`、lift–displacement 相位、每周期流体功
`W_f=int F_y' y_dot dt`、结构能量收支及 2S 尾流特征。首个锁定点的最小范围建议为 20 个 `T_n=5.2 s`（104 s，20,800 步）；前 10 周期只作起振段，后 10 周期才可作统计。到此上限仍未形成可定义的统计状态即停止，不自动延长。

在主算例有效后，才分别申请：一档网格改变、`dt/2` 短再现段、及邻近 `U_r` 的单点敏感性。它们每项只能改变一个因素，且不得用于“调参获得锁定”。不提供墙钟时间估计。

## 与三切片放大的判别关系

| 假设 | 单切片试验如何判别 | 已有证据如何使用 |
|---|---|---|
| 初始流场/通量投影 | 固定与零运动动态起点的合法性在 FSI 起动前单独记录；不以人工 compatible-Uf 作为生产初值 | 已知首步差主要来自 `Uf` 重建/CorrectPhi；不再重复该反事实 |
| 流体附加质量与耦合稳定性 | 比较 SDOF 能量、频率偏移、每周期功与耦合迭代/时间步敏感性；不得仅以振幅增长命名为附加质量不稳定 | 三切片 W10 力身份一致，未证明附加质量机制 |
| 结构质量/阻尼 | 自由衰减先给出独立解析基准；FSI 只改变流体载荷 | 不使用 50 m 立管的总质量、刚度或 Rayleigh 阻尼作替代 |
| 力单位和映射 | 强制 `N ↔ N/m ↔ N`、单位展向长度、虚功及瞬时功率检查 | 已有三切片 mapping/virtual-work 证据作为接口检查，不重新猜测根因 |
| 时间层与离散 | 每个输出记录输入位移、力采样层、结构更新和 CFD 时间；只在物理窗口提交后统计 | V2 已关闭规定运动 participant 的一层错位；不外推为三切片根因 |

## ANCF 的位置

当前 ANCF C++ 核心不能直接被称为“该圆柱 SDOF 的结构模型”：其现有边界、杆/梁几何、质量分布和多自由度与此合同不同。后续若要接入，须另行设计一个受约束单广义坐标模型，证明其线性化 `M,C,K` 等于本表 `m',c',k'`，并重复步骤 1 的自由衰减。否则仅将独立 SDOF 用作 CFD/FSI 诊断对照，不把结果嫁接到 ANCF 物理验证。

## 当前状态和后续授权

本轮结束后等待人工选择是否首先授权“步骤 1：独立 SDOF 自由衰减”。该选择不会授权 CFD、preCICE、ANCF 生产耦合、三切片 0.05 s 重跑或长时间 VIV。

```
NEXT_SINGLE_SLICE_SDOF_FREE_DECAY = PENDING_HUMAN_AUTHORIZATION
NEXT_SINGLE_SLICE_FREE_FSI = NOT_AUTHORIZED
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

## 文献入口

* A. Placzek, J.-F. Sigrist & A. Hamdouni, “Numerical simulation of an
  oscillating cylinder in a cross-flow at low Reynolds number: Forced and free
  oscillations,” *Computers & Fluids* 38 (2009) 80–100,
  [DOI](https://doi.org/10.1016/j.compfluid.2008.01.007).
* G. Tang et al., “Numerical Simulation of Vortex-Induced Vibration with
  Three-Step Finite Element Method and Arbitrary Lagrangian-Eulerian
  Formulation,” *Advances in Mechanical Engineering* (2013),
  [DOI](https://doi.org/10.1155/2013/890423).
* T. K. Prasanth & S. Mittal, “Vortex-induced vibrations of a circular cylinder
  at low Reynolds numbers,” *Journal of Fluid Mechanics* 594 (2008) 463–491,
  [DOI](https://doi.org/10.1017/S0022112007009202).
