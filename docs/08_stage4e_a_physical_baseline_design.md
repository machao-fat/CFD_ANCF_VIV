# Stage 4E-A 物理基线与 ANCF 参数设计

## Frozen project identity

协议 `0.2.1` 与三切片 manifest identity `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3` 保持不变。当前工程为 `L=10 m, D=1 m, dInner=0.9 m, E=2.07e11 Pa, topTension=1e7 N`，三切片速度为 0.8/1.0/1.2 m/s，`rho_f=1025 kg/m³` 用于结构湿质量比审计；正式 CFD 参数仍以既有协议为准。

## Dimensionless mapping

采用：

`Re=UD/nu`、`Ur=U/(f_n D)`、`m*=m/(rho_f*pi*D²/4)`、`Sc=2m*zeta`、`EI*=EI/(rho_f U²D³)`、`EA*=EA/(rho_f U²D²)`、`T*=T/(rho_f U²D²)`、`St=f_sD/U`。

VIVdatashare 双向剪切候选（取 `Umax=0.48 m/s`、假设水的 `nu=1e-6 m²/s` 仅作示例）为：

- `L/D=268.9194`；
- `m*=1.9561`（rho=1000），`m*=1.9084`（rho=1025）；
- `Re≈13615`；
- `Sc≈0.1009`，仅由来源给出的 `zeta=2.58%` 计算；
- `EI*≈1.11e4`、`EA*≈1.10e8`、`T*≈5.28e3`（rho=1000，U=0.48）。

冻结工程的湿质量比约 `1.4551`，`L/D=10`。三个既有 developed-flow 频率对应的 `St` 约为 0.1342、0.1415、0.1486；使用 nElem=4 dry first frequency `27.5093 Hz` 的 `Ur` 约为 0.0291、0.0364、0.0436。工程模型与公开高 Re 长柔性管在 L/D、Re、EI*、T*、Ur 和阻尼上均不相似，因此不得把当前工程结果包装为实验相似性已满足。

优先级建议：先锁定流场拓扑与边界条件，再锁定湿质量/附加质量和频率位置，随后由来源证据确定阻尼/Scruton，最后才比较 EI/EA/T 无量纲组和 Re。不能为达到相似性随意调 E、T 或 damping。

## ANCF structural design

离线调用只读生产函数：`vertical_ttr_case`、`ancf_initialize`、`ancf_constraints`、`ancf_internal_force_tangent`、`ancf_shape`。设计网格为 nElem=2/4/8/16，节点数分别 3/5/9/17，自由度分别 18/30/54/102；不同 nElem 不直接比较 q 向量，而是在共同 201 点弧长网格比较频率、模态形状和静态构型。

冻结工程的 nElem=2/4/8/16 第一频率为：

`27.608046, 27.509346, 27.502842, 27.502430 Hz`。

第三频率为：

`120.728439, 109.268546, 108.869957, 108.843672 Hz`。

4 与 8 单元的前三个主要模态频率变化满足 2% 级别，主要模态 common-span MAC 大于 0.9999；但保留模态集合的全模态最大频率误差约 11.86%，未满足严格全模态 1% 目标。因此 Luna 不冻结最终生产 nElem，也不把“主要模态诊断通过”升级成全模态离散收敛通过。

VIVdatashare 参数在同一只读核心下的 nElem=4 第一频率约 1.84813 Hz；其 4 与 8 的前三主要模态通过 2% 级频率和 0.99 MAC 诊断，但全模态最大频率变化约 8.36%，同样不能作为全模态 1% 通过。

## Dry/wet frequency separation

本报告将三类量严格分离：

1. `dry ANCF frequency`：由结构质量矩阵和线性化切线得到，不含未证实的流体附加质量；
2. `experimental reported frequency`：只按来源原样保存，若来源未标 dry/wet，则标为 `state_unresolved`；
3. `approximate wet candidate`：取 `Ca=0.5/1.0/1.5` 的附加质量敏感性估计，不是实验频率。

VIVdatashare 候选 nElem=16 dry first frequency约 1.84812 Hz，对应 Ca=0.5/1.0/1.5 的第一频率估计约 1.64931/1.50337/1.39038 Hz。冻结工程 nElem=16 dry first frequency约 27.50243 Hz，对应相同 Ca 候选约 23.72651/21.17309/19.29892 Hz。以上仅为诊断灵敏度，不授权修改当前模型。

## Two-dimensional slice limits

二维切片只能表达局部二维绕流和通过 H/Hᵀ 的结构耦合，不能自动表达三维相关长度、端部效应、跨切片尾迹相干性、沿程压力恢复和真实剪切流之间的三维相互作用。公开高长细比实验中的高模态/行波现象因此只能作为分级验证目标，不能由三切片低 Re 结果外推。

## Cost projection

以 Stage 4D-B 实测 3 切片、100 步、300 次 OpenFOAM 执行、约 720.263 s、约 577 MB 为基准，在并发上限 2 下，1 s 物理时间的线性估算为：

| 场景 | 切片 | dt | 步数 | 执行次数 | 估算墙钟 | 估算存储 |
|---|---:|---:|---:|---:|---:|---:|
| minimum | 3 | 0.0025 s | 400 | 1200 | 0.80 h | 2.31 GB |
| recommended | 5 | 0.00125 s | 800 | 4000 | 2.67 h | 7.69 GB |
| high-risk | 8 | 0.00125 s | 800 | 6400 | 3.20 h | 12.30 GB |

这是容量/排程估算，不是实际性能保证；5/8 切片还需要独立充分发展流场来源，不能复制三组流场伪造。

## Decision boundary

本阶段结论为 `partially_completed`。公开数据候选、物理映射和离线 ANCF 证据已形成，但 primary 尚未冻结；严格全模态 4/8 单元 1% 目标未通过；未授权真实 CFD。机器结果见 `results/08_stage4e_physical_baseline/`。
