# 阶段一 ANCF 模块修改边界与实施指导

日期：2026-08-04  
项目根目录：`D:\研二文件\开题准备\CFD_ANCF_VIV`

## 1. “阶段一 ANCF 重构模块未修改”的准确含义

这句话不是说 ANCF 模块不能修改，也不是说阶段一代码已经完成了阶段二所需的全部功能。它的准确含义是：在建立固定圆柱 CFD 基线的这一轮工作中，没有直接改写

```text
src/structure_ancf_matlab/*.m
```

中的任何 MATLAB 实现，也没有改动课题组原始 ANCF 程序包。固定圆柱 CFD、网格、后处理和文档工作先独立完成，阶段一 ANCF 回归测试仍保持原有基线；实际回归结果为通过，切线有限差分误差 `7.244e-7`、虚功误差 `0`、重启误差 `0`。

阶段二任务 0 确实需要对重构模块做“可追踪的增量修改”，例如稀疏矩阵、轴力状态标签和更完整输出。但这些修改必须单独记录、可回退，并通过“修改前基线 vs 修改后版本”的逐项比较后才能进入 CFD 耦合。

## 2. 建议向课题组说明的修改原则

可以直接这样说明：

> 阶段一 ANCF 重构模块先作为受保护基线，不直接覆盖或改写原始程序包。阶段二只在独立重构目录上增加可选的稀疏装配、求解器配置和低张力状态后处理；保持既有公共函数和 CSV 字段兼容，用新增字段和新增测试扩展功能。每次修改先运行阶段一回归，再与稠密基线逐项比较；若数值或物理结果不一致，立即回退到基线，不把差异解释为模型更准确。

## 3. 允许修改的位置和推荐顺序

### 3.1 稀疏装配与求解

当前主要位置是：

- `src/structure_ancf_matlab/ancf_mass_matrix.m`：质量矩阵目前从 `zeros(ndof,ndof)` 开始装配；
- `src/structure_ancf_matlab/ancf_internal_force_tangent.m`：切线刚度目前从 `zeros(ndof,ndof)` 开始装配；
- `src/structure_ancf_matlab/ancf_advance_step.m`：当前使用 `Keff(free,free)\R(free)`，但 `Keff` 由稠密矩阵产生。

推荐不要改变公共函数签名，而是在 `model.numerics` 增加配置，例如：

```matlab
model.numerics.matrix_mode = 'dense';   % 基线
model.numerics.linear_solver = 'backslash';
```

然后实现两个内部路径：

1. `dense`：保留现有代码，作为逐项回归基线；
2. `sparse`：用 `sparse(i,j,v,ndof,ndof)` 或稀疏局部块累加装配 `M`、`Kint` 和 `Keff`。

第一步只改装配格式和存储类型，不同时改变时间积分、Newton 容差、边界条件或材料公式。小模型必须比较：`q`、`qd`、`qdd`、内力、残差、Newton 次数和时间步数；随后再用接近多切片规模的 `nElem` 做内存/耗时基准。

### 3.2 轴力定义和低张力标签

当前 `ancf_postprocess.m` 已同时输出：

```matlab
material_axial_force_N = EA * Green_strain
tension_N              = EA * Green_strain * norm(r_s)
```

报告中应明确：前者是材料/参考构形量 `EAε`；后者是沿当前切线方向投影后的当前轴力幅值。低张力状态建议使用 `tension_N` 作为判据，同时保留两种量，不能把二者混称。

推荐新增独立后处理函数，例如 `ancf_axial_state.m`，在每个单元中心或高斯点上输出：

```text
time_s, step, element_id, s_ref_m,
material_axial_force_N, current_axial_force_N,
curvature_1pm, state_label
```

状态阈值必须写入模型配置而不是散落在代码中：

- `taut`：轴力大于近零阈值；
- `near-slack / incipient buckling`：轴力接近零或稳定性指标可疑；
- `compression-risk`：出现负轴力。

`compression-risk` 只能作为“当前模型可能进入受压/松弛/屈曲风险区”的标签，不能作为顶张式立管稳定状态或有效 VIV 预测结论。

同时汇总每个时间步和全程的最小轴力、持续时间、发生单元/位置、最大曲率和最大斜率。旧字段不删除，只新增状态字段，保证已有 CSV 和 MATLAB 测试仍可读。

## 4. 必须保留的验证证据

每一次修改都应按下列顺序执行：

1. 阶段一原有 `tests/structure_ancf_matlab/test_vertical_ttr_solver.m`；
2. 解析切线、虚功、收敛、checkpoint/restart 和旧程序包对比测试；
3. 新增 `tests/structure_sparse/` 中的 dense/sparse 等价性测试；
4. 低张力专门测试，确认负轴力只触发标签而不被自动解释成有效张紧工况；
5. 结果保存到 `results/03_structure_hardening/`，不覆盖阶段一已有结果。

若 sparse 版本暂时不稳定，可以保留稠密基线，并只增加 `matrix_mode` 接口和性能测试；这比为了“完全稀疏化”破坏已通过的 ANCF 回归更安全。

## 5. Gmsh 的使用边界

已核对 Gmsh：

```text
版本：4.14.1
程序：D:\Gmsh\gmsh-4.14.1-Windows64\gmsh-4.14.1-Windows64\gmsh.exe
```

OpenFOAM 10 的 `gmshToFoam` 也已确认可用。后续网格敏感性研究建议在独立目录生成 `coarse/medium/fine` 三档 `.msh`，转换后逐一运行 `checkMesh`；不要覆盖当前已经跑通的 `blockMesh` 基线。Gmsh 网格必须明确圆柱壁、入口、出口、上下边界和前后 `empty` 面的物理分组，并检查转换后边界名称和二维单位展向厚度是否仍然正确。
