# 方法对比：VIVdatashare、viv-FOAM-SJTU 与拟开发 CFD–ANCF

## 1. 核心结论

拟开发程序不是 viv-FOAM-SJTU 的复刻版。三者都可能采用 OpenFOAM 和切片思想，但本课题的实质差异是：**保留二维切片的可承受成本，把结构域替换为可描述几何非线性的 ANCF，同时保留一个共享同一 CFD 的线性 Euler–Bernoulli 梁对照，并以虚功一致的转置映射传递载荷，最终输出结构模型适用性边界。**

## 2. VIVdatashare 代码实检

审查对象：[GitHub `VIV_Numerical_Codes/Flexible_pipe`](https://github.com/xuepengfu/VIVdatashare/tree/main/VIV_Numerical_Codes/Flexible_pipe)，本地只读副本位于 `D:\研二文件\开题准备\tmp\VIVdatashare`。

### 2.1 已确认的实现

- 根 README 明确称其为“2D strip method based on Euler beam with constant tension”，要求 OpenFOAM-8、MATLAB 2018、Parallel Computing Toolbox 和 Signal Processing Toolbox。
- `main.m` 默认使用 100 个梁单元/101 个节点、每节点 6 个自由度、11 个 CFD 切片、常张力 550 N、Newmark-beta 参数 `beta=0.25`、`gamma=0.5`，耦合时间步 0.0005 s。
- `stiffnessmatrix.m` 使用经典三维线性 Euler–Bernoulli 梁刚度和由常张力形成的几何刚度；`coordinatetrans.m` 当前返回单位阵，因此没有实现随大转动更新的局部—全局变换。
- OpenFOAM 每个切片由模板目录复制；`system('source runpimpleFoam_bash')` 在每个耦合步推进各切片。
- `forceread.m` 读取 `forceCoeffs.dat`；`main.m` 将切片升阻力系数沿轴向用 MATLAB `spline` 插到结构节点，并按 `0.5 rho U^2 D l C` 形成节点力。
- 结构位移再用独立 `spline` 从结构节点插回 CFD 切片；`transferdis.m` 直接改写各切片 `pointDisplacement` 的圆柱边界平移量。
- 该双向样条并没有显式构造同一个 `H` 与 `H^T`，因此不能仅从代码认定离散虚功守恒。
- 实验目录实际公开的是合同允许分享的双向剪切流选定原始应变和处理代码；README 明确说明其余数据受合同限制。对应论文为 [Fu 等（2025）](https://doi.org/10.1016/j.marstruc.2025.103895)，试验背景见 [Fu 等（2022）](https://doi.org/10.1016/j.jfluidstructs.2022.103722)。

### 2.2 许可证判断

仓库根目录只有 `README.md`、`VIV_Experimental_Results` 和 `VIV_Numerical_Codes`，没有 `LICENSE`、`LICENCE`、`COPYING` 等文件；MATLAB 和 OpenFOAM case 文件也没有发现赋予复制、修改或再发布权利的许可证头。GitHub 页面也未显示许可证。

因此结论是：**VIVdatashare 没有明确开源许可证。公开可见不等于开源授权。** 在未获得作者书面许可前，本课题可以阅读、在合规环境中运行、引用论文和仓库、借鉴公开算法思想；不能默认复制其 MATLAB 实现到新仓库，不能重新许可或随论文附件再发布原代码/受限试验数据。新程序应独立实现，并保留设计记录证明没有逐行移植。

OpenFOAM 本身由 OpenFOAM Foundation 以 GPLv3 发布；当前最新主版本为 [OpenFOAM 14](https://openfoam.org/version/14/)。但 VIVdatashare 固定在 OpenFOAM-8，不能假设 case 字典和脚本可直接迁移到当前版本。

## 3. 详细对比表

| 对比项 | VIVdatashare Flexible_pipe | viv-FOAM-SJTU / viv3D-FOAM-SJTU | 拟开发 CFD–ANCF |
|---|---|---|---|
| 定位 | 2025 论文对应的可分享研究代码，便于复算二维切片 + 线性梁 | 万德成团队的 in-house VIV 求解体系和系列研究 | 面向硕士论文的最小可验证研究平台 |
| CFD 维度 | 多个独立二维切片；OpenFOAM-8 RANS/PIMPLE | 原版为二维切片；后续 viv3D 为有限轴向厚度的三维切片 | 主线仅二维切片；厚切片为可选单工况扩展 |
| CFD 网格运动 | `pointDisplacement` 写入圆柱刚体平移；模板 case 使用动态网格 | 文献报告 Laplace 或 RBF 动网格；RBF 主要用于流体内部网格变形 | 第一版采用圆柱边界刚体平移 + OpenFOAM 动网格；接口与网格运动算法解耦 |
| 湍流/流动模型 | OpenFOAM case 使用 SST 类设置；具体以 case 字典为准 | URANS，常用 SST `k-omega`，PIMPLE | 不可压 URANS 为生产模型；低 Re 单圆柱可用层流做代码验证；固定版本与字典 |
| 结构模型 | 线性三维 Euler–Bernoulli 梁 FEM + 常张力几何刚度 | 线性 Euler–Bernoulli 梁 FEM；2017 文献中轴力可随高度变但不随时间变 | ANCF 几何非线性主模型 + 线性 Euler–Bernoulli 梁 FEM 对照 |
| 结构时间积分 | Newmark-beta，`beta=0.25, gamma=0.5` | 文献报告 Newmark-beta | 由现有 ANCF 程序决定；合同要求隐式迭代信息可见；线性梁先用 Newmark-beta/generalized-alpha |
| 耦合方式 | 每步 CFD → 读力 → MATLAB 梁 → 写位移；弱/松耦合 | 时间域松耦合为主；公开资料未证明每个工况强耦合 | 先实现串行交错基线，再提供可选固定点/Aitken 强耦合；记录迭代残差 |
| 结构到 CFD 运动传递 | 结构节点位移沿轴向 `spline` 到切片；切片内圆柱整体平移 | 结构位移插值到切片；RBF 用于流体网格形变 | `x_slice = H q_s`；线性梁和 ANCF 使用各自形函数构造 `H`，但切片定义和坐标完全一致 |
| CFD 到结构载荷传递 | 切片系数样条到结构节点，再按节点段长形成集中力 | 文献称流体力映射到结构节点，公开论文未给出完整虚功守恒实现细节 | 先把壁面应力积分成每切片的 IL/CF 合力，再按轴向求积权重形成共轭力；`F_s = H^T F_slice` |
| 非匹配节点守恒 | 未显式保证；前后使用独立样条 | 公开资料不足以确认转置/共同积分；不能假定守恒 | 明确要求合力、力矩、虚功/功率残差测试；理论依据见 [Farhat 等（1998）](https://doi.org/10.1016/S0045-7825(97)00216-8)和 [de Boer 等（2008）](https://doi.org/10.1016/j.cma.2008.05.001) |
| 坐标系 | 直立管参考轴，IL/CF 分量；`coordinatetrans.m` 当前为单位阵 | 直立顶张式立管，IL/CF；可处理均匀、剪切、阶梯和振荡流 | 固定全局右手系：`z` 沿未变形立管向上、`x` 为 IL、`y` 为 CF；主线切片不随局部切线旋转 |
| 几何非线性 | 否；刚度矩阵不随构型更新，常张力 | 原版和 2020 厚切片论文仍采用线性梁 | 是；通过 ANCF 应变与曲率产生构型相关内力和张力 |
| 低张力支持 | 可输入较小常张力，但没有低张力大变形结构有效性保证 | 做过顶张力参数研究，但公开结构模型仍基于小斜率线性梁；不能等同于低张力大变形验证 | 研究对象；要求 `T_min`、张力波动和构型变化可输出，并与线性梁对照 |
| 曲线构型 | 未实现一般曲线构型 | 主要为直立顶张直管；后续团队体系可能有其他应用，但本对比只按公开 VIV 论文判断 | ANCF 理论上可扩展，但论文主线明确不做复杂曲线初始构型 |
| IL/CF 双向耦合 | 是 | 是 | 是；轴向结构自由度保留，但二维 CFD 不直接解析轴向流体力 |
| 公开验证 | 论文：均匀、线性剪切、双向剪切；仓库仅分享合同允许的部分数据 | 均匀/剪切、Chaplin 阶梯流、振荡流；viv3D 用 Lehn 均匀流和 Chaplin 阶梯流 | 主验证 Chaplin 阶梯流；备用 Miami II；均匀/线性剪切用于扩展 |
| 计算成本 | 中等；11 个二维切片的每步外部进程/文件 I/O 很重 | 二维版本中等；三维厚切片明显更高 | 二维版本与切片数近似线性增长；ANCF 非线性迭代高于线性梁，但远低于整根三维 CFD |
| 软件可复现性 | 依赖旧 OpenFOAM-8、MATLAB 工具箱和 SJTU HPC 脚本；无测试 | 核心 solver 未发现公开源码，主要可依据论文复现思想 | 版本固定、接口合同、单元测试、基准 case 和自动报告是必做交付 |
| 许可证 | **无明确许可证**；不能默认复制或再发布 | OpenFOAM 部分受 GPL；in-house solver 未发现公开代码许可证 | 新代码许可证由课题组决定；不得混入 VIVdatashare 未授权代码 |

## 4. 可以借鉴的部分

### 4.1 从 VIVdatashare 借鉴

- 多切片目录组织和并行运行思路；
- OpenFOAM `forces/forceCoeffs` 的读取路径与动态边界写入位置；
- Newmark-beta 梁基线和 pinned–pinned 边界处理思路；
- 切片数与结构节点数不同这一实际接口问题；
- 以均匀、线性剪切、双向剪切三类稳态流组织案例的方法。

借鉴必须停留在算法和测试设计层面。新的映射、驱动器和结构程序应从接口合同独立实现。

### 4.2 从 viv-FOAM-SJTU 借鉴

- 二维切片 + OpenFOAM + 线性梁 FEM 的总体基线；
- PIMPLE、SST `k-omega`、IL/CF 双向响应和时间域耦合；
- Chaplin 阶梯流的模型参数与评价量；
- 用 RBF 或其他动网格策略提高大 IL 位移时的网格质量；
- 以 RMS 位移、平均 IL 偏移、主频、模态和曲率进行验证；
- 厚切片只在需要轴向涡相关时启用的分层思路。

## 5. 不能直接照搬的部分

### 5.1 VIVdatashare

- 无许可证代码不能逐行复制、改名后再发布；
- OpenFOAM-8 字典、bash 脚本和 MATLAB 工具箱依赖不应成为新项目架构；
- 每个耦合步调用 shell、暂停并轮询文件的实现成本高且脆弱；
- 常张力线性梁不能回答低张力大变形问题；
- 双向独立样条不满足本项目的虚功一致验收标准；
- 默认参数和网格属于特定试验，不能作为普适标定值。

### 5.2 viv-FOAM-SJTU

- 核心 in-house solver 未公开，不能把论文描述等同于可复用代码；
- 线性梁和预设张力限制了本论文要研究的结构非线性；
- RBF 动网格不等于流固界面的守恒载荷映射，两者不能混为一个创新点；
- 厚切片增加的是流场保真度，不直接解决结构低张力适用性；
- 团队长期功能（平台运动、振荡流、复杂参数）不应全部进入本硕士范围。

## 6. 拟开发工作的创新定位

| 潜在创新 | 与既有工作的差异 | 必须提供的证据 |
|---|---|---|
| 同一 CFD 下的 ANCF/线性梁对照 | 既有二维切片工作通常只用线性梁；ANCF 海工工作通常不与同一高保真 VIV CFD 做受控对照 | CFD 载荷、网格、时间步、阻尼和边界完全一致；只切换结构适配器 |
| 切片合力到 ANCF 广义力的转置映射 | 既有代码多描述“插值”，未必公开虚功测试 | 合力、力矩、随机虚位移和瞬时功率残差达到预定容差 |
| 低张力/大变形适用性边界 | 不是证明 ANCF 总是更好，而是找出线性模型何时仍足够 | 无量纲参数扫描、网格/时间步/切片数不确定性，以及实验锚点 |
| 负结果也可解释 | 高张力区两模型接近本身就是边界的一部分 | 报告计算成本和等价区，避免只挑差异最大的工况 |

## 7. 推荐的实现顺序

1. 先实现与结构无关的二维圆柱 CFD case 和标准化 `slice_motion`/`slice_loads` 文件。
2. 先接线性梁 FEM，复现一个公开切片基线；不要一开始就调 ANCF。
3. 实现 `H`、`H^T` 和虚功单元测试，再增加 CFD 数量。
4. 取得课题组 ANCF 程序后只写适配层，使其遵守同一接口合同。
5. 用载荷回放先比较两种结构模型，再开启完整双向耦合。
6. Chaplin 高张力系列用于基准验证，低张力系列用于检查非线性趋势；最后再做更低张力的数值探索。
