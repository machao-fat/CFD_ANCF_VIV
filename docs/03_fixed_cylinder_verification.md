# 固定二维圆柱 OpenFOAM 基准：首轮可复现实测报告

日期：2026-08-04  
项目根目录：`D:\研二文件\开题准备\CFD_ANCF_VIV`

## 1. 结论边界

首轮中等网格结果曾经只能作为预备基线；随后已用 Gmsh 4.14.1 在独立 study 根目录完成三档网格、两档时间步的敏感性研究，并将代表工况从 `t=0` 完整计算到 `t=30 s`。固定圆柱流场稳定，三档网格均通过当前项目网格质量阈值，medium 网格的两档时间步结果几乎重合。因此，任务 1 的最低准入条件现在达到，可以进入规定运动圆柱接口工作；但该结论不是“高精度实验验证”，最终建议使用 fine 网格并保留网格差异和文献差异作为不确定性说明。

## 2. 环境与复现记录

| 项目 | 记录 |
|---|---|
| 操作系统 | Windows 主机 + WSL2 Ubuntu 22.04 |
| OpenFOAM | Foundation OpenFOAM 10，构建标识 `10-c4cf895ad8fa` |
| 编译器 | WSL GCC 11.4.0；OpenFOAM 构建选项 `linux64GccDPInt32Opt` |
| 求解器 | `icoFoam`，二维不可压层流固定圆柱 |
| 工况 | `D=1 m`，`U∞=1 m/s`，`rho=1000 kg/m^3`，`nu=0.01 m^2/s`，`Re=100` |
| 计算厚度 | `Lz=1 m`，前后面 `empty`，代表单位展向厚度 |
| 时间推进 | 一阶 Euler，`dt=0.0025 s`，`t_end=30 s` |
| 网格 | 首轮 blockMesh 基线为 5120 个单元；最终敏感性 study 使用 Gmsh coarse/medium/fine，分别为 1772/3268/8360 个单元；上游约 `5D`、下游约 `10D`、横向约 `5D` |
| 启动场 | `setFields` 在 `0.5D<x<2D`、`|y|<0.4D` 区域加入 `Uy/U∞=0.1` 的数值触发种子；入口边界没有改变 |
| 复现入口 | 在案例目录执行 `./Allrun`；已有输出需先执行 `./Allclean` |

OpenFOAM 官方 v10 发布说明明确了该版本及其构建/环境背景；本项目固定使用该版本，不混用其他版本案例语法。[OpenFOAM Foundation v10 release](https://openfoam.org/release/10/)

Windows PowerShell 中的复现命令：

```powershell
wsl.exe bash -lc 'source /opt/openfoam10/etc/bashrc; cd /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/fixed_cylinder; ./Allclean; ./Allrun'
```

尾涡图的离线生成命令见案例 [README.md](../cases/openfoam/fixed_cylinder/README.md)。

## 3. 网格和时间步检查

`checkMesh -allGeometry -allTopology -meshQuality` 的主要记录为：

| 量 | 实测值 |
|---|---:|
| cells | 5120 |
| faces | 20672 |
| internal faces | 10048 |
| 最大非正交角 | 42.39° |
| 平均非正交角 | 9.02° |
| 最大 skewness | 0.28 |
| 最小面面积 | `4.686e-4 m^2` |
| 最小单元体积 | `4.686e-4 m^3` |
| 最小面插值权重 | 0.031488 |

项目 `system/meshQualityDict` 将本阶段显式记录的插值权重阈值设为 `0.03`，在该项目阈值下没有新增违规面；但 OpenFOAM 默认报告仍显示 34 个面低于默认 `0.05`，日志末尾为 `Failed 1 mesh checks.`。这应被视为网格改进项，而不是被“放宽阈值”后宣称网格完全通过。

首轮 blockMesh 最大 CFL 约为 `0.185`；Gmsh final study 中最大 CFL 为 `0.262`，仍低于本案例采用的稳定运行上限，且没有观察到时间推进发散。最终 study 统一采用 `15 s≤t≤30 s` 统计窗口，避免把短时启动瞬态的频谱分辨率误认为脱涡主频。

## 4. 首轮水动力结果

结果文件位于 [results/03_fixed_cylinder/medium](../results/03_fixed_cylinder/medium)。统计窗口是 `15 s≤t≤30 s`，共 12001 个力样本。

| 量 | 首轮结果 |
|---|---:|
| `Cd_mean` | 1.46634 |
| `Cl_mean` | -0.00668 |
| `Cl_rms` | 0.29232 |
| `Cl` 半峰峰值 | 0.54499 |
| 主频 `f` | 0.16071 Hz |
| `St=fD/U` | 0.16071 |

公开 Re=100 二维圆柱基准的共同趋势是 `St` 约 `0.16–0.17`、平均阻力系数约 `1.33–1.40`；升力幅值会随边界、网格和定义变化，不能把不同文献的幅值定义混为一谈。相关数值基准可见 [Fu et al. (2015)](https://doi.org/10.1155/2015/568176) 和 [Jiang & Cheng (2017)](https://doi.org/10.1017/jfm.2017.685)。首轮 blockMesh 结果的 `St` 与基准趋势一致但 `Cd_mean` 略高，因此当时只判为预备基线；最终准入以 4.1 节的 Gmsh 敏感性研究为准。

尾涡瞬态图：

- [t=25 s 涡量图](../results/03_fixed_cylinder/medium/vorticity_t25.png)
- [t=30 s 涡量图](../results/03_fixed_cylinder/medium/vorticity_t30.png)

这些图由 OpenFOAM `postProcess -func vorticity`、`foamToVTK` 和 ParaView 510 离线脚本生成；不是手工绘图。Gmsh fine study 的尾涡图见 [fine 网格 t=30 s](../results/03_fixed_cylinder/sensitivity_full30b/fine_dt0p0025/vorticity_t30.png)。

### 4.1 Gmsh 三档网格与两档时间步敏感性

完整结果位于 [sensitivity_full30b](../results/03_fixed_cylinder/sensitivity_full30b)，所有表中数据均来自从 `t=0` 开始的完整运行，统计窗口为 `15–30 s`。

| 网格/时间步 | cells | `Cd_mean` | `Cl` 半峰峰值 | `St` | 最大 CFL |
|---|---:|---:|---:|---:|---:|
| coarse / 0.0025 s | 1772 | 1.37864 | 0.15410 | 0.13903 | 0.10031 |
| medium / 0.0025 s | 3268 | 1.40753 | 0.28274 | 0.15009 | 0.15979 |
| fine / 0.0025 s | 8360 | 1.41865 | 0.28850 | 0.17142 | 0.26224 |
| medium / 0.00125 s | 3268 | 1.40707 | 0.28215 | 0.14981 | 0.07993 |

medium 网格两档时间步的相对差异为：平均阻力约 0.03%，升力半峰峰值约 0.21%，`St` 约 0.19%，说明 `dt=0.0025 s` 在 medium 网格上已基本时间步收敛。网格加密后平均阻力和升力幅值向细网格结果变化，fine 网格的 `St=0.1714` 与 Re=100 文献趋势一致；coarse 网格的升力和主频明显偏低，因此不作为后续耦合网格。

该表说明“趋势和数值稳定性达到最低准入”，但不应被解读为 ANCF 或 OpenFOAM 已经完成高精度实验验证。后续规定运动和耦合应优先使用 fine 网格，并继续记录网格不确定性。

## 5. 输出文件与检查项

- `forces.csv`：圆柱壁压力力、黏性力、总力和力矩，SI 单位 N/N·m；
- `force_coeffs.csv`：`Cd`、`Cl` 和力矩系数；
- `residuals.csv`：每个时间步的方程残差；
- `cfl.csv`：平均/最大 Courant 数；
- `force_history.png`、`lift_spectrum.png`：力时程和升力频谱；
- `summary.json`：后处理窗口和关键无量纲结果；
- `log.blockMesh`、`log.checkMesh`、`log.setFields`、`log.icoFoam`：完整运行证据。

后处理脚本对时间列、有限数值和样本数量作基本检查；固定圆柱案例的 CSV 接口仍然是独立于阶段二 ANCF 文件交换协议的 CFD 侧输出，下一步会在规定运动任务中统一列名和切片元数据。

## 6. 二维力的量纲闭合与手工验算

本案例的计算域展向厚度为 `Lz=1 m`，因此 `forces` 积分得到的是该有限厚度上的总力，单位为 N。对二维单位展向结果可定义

```text
f_2D [N/m] = F_OpenFOAM [N] / Lz [m]
F_slice [N] = f_2D [N/m] * l_slice [m]
```

手工验算：若某一时刻 OpenFOAM 对 `Lz=1 m` 输出总力 `F_OpenFOAM=100 N`，则 `f_2D=100 N/m`。若 ANCF 切片代表长度为 `l_slice=0.25 m`，回传力是 `F_slice=100×0.25=25 N`。不能把已得到的 `25 N` 再乘 `0.25 m`，也不能把 `100 N` 直接当作 `25 m` 切片的力。后续转换器必须只执行一次 `f_2D*l_slice`，并在 CSV 元数据中记录 `unit_span_m` 和 `slice_length_m`。

## 7. 当前准入判定

| 条件 | 状态 |
|---|---|
| 固定圆柱流场有稳定交替尾涡 | 满足 |
| `St` 与可靠基准趋势一致 | 满足最低趋势要求；fine 最接近 |
| `Cd`、升力幅值定量收敛 | 满足最低敏感性要求；网格差异保留为不确定性 |
| 三档网格 | 已完成：1772/3268/8360 cells |
| 两档时间步 | 已完成：medium 网格 0.0025/0.00125 s |
| 网格质量无警告 | Gmsh study 通过；首轮 blockMesh 仍保留历史低权重提示 |
| 力的 N 与 N/m、切片长度换算闭合 | 已建立并记录 |

因此，固定圆柱任务 1 已达到阶段二最低准入标准，可以进入任务 2 的规定运动圆柱和 CFD–CSV 接口；仍不得把该结果写成整根柔性立管 VIV 验证，也不得跳过规定运动接口直接宣称自由耦合可信。
