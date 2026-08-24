# 动网格方法选型审查

日期：2026-08-04

结论：**第三阶段默认使用 OpenFOAM 10 原生 `interpolatingSolidBody`**，暂不移植旧 OpenFOAM 2.3.0 RBF。现有 `solidBody + cellZone` 只保留为低振幅对照：在 A/D=0.1 可以完成 20 s，但在 A/D=0.3 和 0.5 分别于 0.425 s 和 0.25 s 浮点异常终止。

## 1. 动网格字典和可复现性修正

OpenFOAM Foundation 10 的 `solidBodyMotionFunction` 从其类型对应的系数字典读取 `amplitude` 和 `omega`。因此新算例统一使用：

```text
solidBodyMotionFunction oscillatingLinearMotion;
oscillatingLinearMotionCoeffs
{
    amplitude (0 A 0);
    omega     2*pi*f;
}
```

原生方案的 mover 为：

```text
motionSolver    interpolatingSolidBody;
patches         (cylinder);
CofG            (0 0 0);
innerDistance   0.75;
outerDistance   2.50;
```

动网格字典必须保留标准 `FoamFile` 头。补查中曾经有一个 run3 生成器遗漏该头，OpenFOAM 实际按静止网格运行，导致六组力时程完全相同；该 run3 已保留作配置审计记录，但不进入结论。`prepare_cases.ps1` 已补回字典头，run4 是有效重跑。

## 2. 比较矩阵

run4 使用相同 expanded medium 网格（16,244 个棱柱单元）、`Re=100`、`dt=0.0025 s`、`f=0.16 Hz`、pimpleFoam 和 `linearUpwind` 对流格式。振幅为 A/D=0.1、0.3、0.5，统计力学窗口为 5--20 s；相位/功率审计按完整周期 6.25--18.75 s 取 2 个周期，因此高振幅相位只作为方法筛选证据，不作为长时间定量物理结论。

结果主文件：

- `results/03_dynamic_mesh_comparison/run4/phase_comparison_summary.csv`；
- 每个算例的 `force/summary.json`、`mesh/summary.json`、`phase_summary.json`；
- 原始 OpenFOAM 日志位于 `cases/openfoam/prescribed_motion_extended/prepared_dynamic_mesh_comparison_run4/`。

| 方法 | A/D | 完成 20 s | 最大 CFL | 最小 determinant | 最大非正交性 | 最大 skewness | 最小体积 m^3 | `Cd_mean` | `Cl` 半峰峰值 | 相位 vs y | 平均功率 W | wall clock |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| solidBody + cellZone | 0.1 | 是 | 0.17132 | 0.25798 | 52.18° | 0.61525 | 1.5911e-3 | 1.43109 | 0.53707 | 61.22° | 10.835 | 432 s |
| solidBody + cellZone | 0.3 | 否，0.425 s | 2.457e87（失败前） | 未写出 | 未写出 | 未写出 | 未写出 | 未统计 | 未统计 | 未统计 | 未统计 | 12 s |
| solidBody + cellZone | 0.5 | 否，0.25 s | 8.275（失败前） | 未写出 | 未写出 | 未写出 | 未写出 | 未统计 | 未统计 | 未统计 | 未统计 | 7 s |
| interpolatingSolidBody | 0.1 | 是 | 0.17132 | 0.52991 | 30.64° | 0.50321 | 1.5911e-3 | 1.43139 | 0.53076 | 62.12° | 10.830 | 437 s |
| interpolatingSolidBody | 0.3 | 是 | 0.18148 | 0.52991 | 32.69° | 0.50347 | 1.5911e-3 | 1.69385 | 0.50012 | 82.31° | 27.071 | 438 s |
| interpolatingSolidBody | 0.5 | 是 | 0.19330 | 0.52991 | 39.30° | 0.50372 | 1.5911e-3 | 1.88601 | 0.18832 | -35.89° | -3.363 | 436 s |

原生方法在三个目标振幅均完成，且几何质量指标保持正 determinant、正体积和可控非正交性。A/D=0.5 的力学量已经表现出明显非线性，平均功率为负并不自动代表物理错误；它只说明在短统计窗内流体对规定运动的净功方向发生变化，必须用更长的周期统计和自由结构响应进一步判断。

## 3. 近壁层和 checkMesh 解释

近壁第一层指标由圆柱壁面 face center 到相邻 owner-cell center 的径向投影距离计算。run4 有效算例的 audit 范围约为 `0.01874--0.02735 m`；原生方案的平移插值不会改变近壁层的基本厚度。

Gmsh 二维挤出棱柱网格的 `checkMesh` 可能写出 `non-aligned edges` 和 `Failed 1 mesh checks`。该信息已逐时间点保留在 `checkMesh/checkMesh_*.log`。本报告没有把它隐藏，也没有把它直接等同于动网格失败；几何有效性根据最小体积、最大非正交性、最大 skewness、cell determinant、cell volume 和 face-pyramid 等核心检查单独判断。原生三种振幅的核心几何检查均通过。

## 4. 选型决定和限制

1. 第三阶段默认：expanded 域 + medium 起步，原生 `interpolatingSolidBody`，`innerDistance=0.75D`、`outerDistance=2.5D`，固定 `dt`，并持续输出 CFL、网格 determinant、体积和近壁层指标。
2. A/D=0.1 的两种方法力学量接近，但原生方法的 determinant 和非正交性余量更好；A/D=0.3、0.5 时现有 `solidBody` 已失效，不能用于后续自由耦合。
3. 原生方法在当前测试的 A/D=0.5 内可运行；若第三阶段目标振幅超过 0.5，必须先做短时网格质量预检和小步长试算，不能直接外推。
4. 目前没有证据要求 RBF。只有当原生方法在论文目标振幅下经步长、外层迭代和域/网格检查后仍失败，才单独提出 RBF 任务；不移植旧版 OpenFOAM 2.3.0 代码作为默认方案。
5. 规定运动阶段的相位和功率结果不能被写成自由 VIV 锁定、结构自激或整根柔性立管预测结论。
