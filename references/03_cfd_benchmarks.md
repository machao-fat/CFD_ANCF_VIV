# 固定圆柱 CFD 基准来源

## 1. 本项目采用的基准

首个案例为无界近似外流场的二维圆柱，`Re=100`。对照只比较同一物理设定下的趋势和量级，不把存在明显通道堵塞比的基准直接套用到本案例。

目标参考范围：

| 量 | Re=100 的无界二维圆柱参考量级 | 本项目用途 |
|---|---:|---|
| 平均阻力系数 `Cd_mean` | 约 `1.33–1.40` | 网格/时间步准入的量级检查 |
| 升力系数主幅值 | 约 `0.30–0.34` | 检查交替脱涡和幅值 |
| Strouhal 数 `St` | 约 `0.16–0.17` | 频率和时间分辨率检查 |

这些数值范围由公开文献中对 Re=100 二维圆柱的汇总表支持，例如 Fu et al. 的公开文章给出了 `Cd≈1.33–1.38`、`St≈0.166` 的网格比较；Delft 公开学位论文的汇总也给出了 `Cd≈1.33–1.35`、`St≈0.164–0.165` 的体拟合/高阶数值结果：[Fu et al. (2015), DOI 10.1155/2015/568176](https://doi.org/10.1155/2015/568176)，[Delft dissertation table](https://pure.tudelft.nl/ws/portalfiles/portal/161113610/Dissertation_print_final.pdf)。Jiang and Cheng 对低 Re 圆柱的 `St-Re` 关系给出更系统的二维/三维 DNS 讨论：[Jiang & Cheng (2017), DOI 10.1017/jfm.2017.685](https://doi.org/10.1017/jfm.2017.685)。

## 2. 不直接套用的经典通道基准

Schäfer et al. 的 DFG 圆柱基准是重要的不可压 Navier–Stokes 数值基准，但其通道高度和圆柱直径给出显著堵塞比，Re=100 的 `Cd` 与无界外流场并不相同。因此本项目将其作为边界条件、力定义和数值验证方法的参考，而不是把其 `Cd` 数值直接当作本案例验收值：[Schäfer et al. (1996), DOI 10.1007/978-3-322-89849-4_39](https://doi.org/10.1007/978-3-322-89849-4_39)。

## 3. 量纲与力输出依据

OpenFOAM Foundation 的 v10 发布说明确认 v10 的物性组织方式和 WSL 支持：[OpenFOAM 10](https://openfoam.org/release/10/)。OpenFOAM `forceCoeffs` 的官方类说明指出它在 `forces` 基础上输出升力、阻力和力矩系数，并要求 `magUInf`、`lRef` 和 `Aref` 等参考量：[forceCoeffs class reference](https://cpp.openfoam.org/v4/classFoam_1_1functionObjects_1_1forceCoeffs.html)。

本项目额外保留 `forces` 的压力力 `pressure`、黏性力 `viscous` 和力矩输出，以便后续转换为 CSV 载荷协议。
