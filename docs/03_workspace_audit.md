# 阶段二工作区审计与固定圆柱启动记录

日期：2026-08-03  
项目根目录：`D:\研二文件\开题准备\CFD_ANCF_VIV`

## 1. 当前目录清单

本次启动前，项目已有内容如下。`cases/openfoam`、阶段二结果目录和阶段二接口目录此前尚未形成；本次首先补建固定圆柱案例。

```text
cases/
  vertical_ttr_ancf_mvp/
    run_structure_replay.m
docs/
  01_interface_contract.md
  01_mathematical_model.md
  01_method_comparison.md
  01_risk_and_schedule.md
  01_scope_and_literature.md
  01_validation_data_plan.md
  02_ancf_phase1_plan.md
  02_ancf_phase1_report.md
references/
  literature_matrix.csv
src/
  structure_ancf_matlab/
    ancf_advance_step.m
    ancf_base_load.m
    ancf_build_mapping.m
    ancf_constraints.m
    ancf_element_energy.m
    ancf_external_load.m
    ancf_gauss_points.m
    ancf_initialize.m
    ancf_initial_configuration.m
    ancf_internal_force_tangent.m
    ancf_load_checkpoint.m
    ancf_mass_matrix.m
    ancf_postprocess.m
    ancf_read_slice_loads_csv.m
    ancf_save_checkpoint.m
    ancf_shape.m
    ancf_slice_motion.m
    ancf_static_equilibrium.m
    ancf_write_slice_motion_csv.m
    README.md
    vertical_ttr_case.m
tests/
  structure_ancf_matlab/
    test_ancf_convergence.m
    test_ancf_legacy_comparison.m
    test_ancf_low_tension.m
    test_ancf_physics.m
    test_ancf_tension_sweep.m
    test_vertical_ttr_solver.m
data/
figures/
results/
```

阶段一报告确认：重构模块独立于课题组原始 `ANCF\Run4v4_wuzfv2` 程序包；原始程序包不复制、不改名、不重新发布。

## 2. 可直接复用的接口

| 用途 | 现有接口 | 阶段二约束 |
|---|---|---|
| 建立结构模型 | `vertical_ttr_case('nElem',...,'nSlices',...)` | 保持 SI 单位和既有切片位置 |
| 初始化 | `ancf_initialize(model)` | 初始化阶段不混入 CFD 载荷 |
| 单步推进 | `ancf_advance_step(state, slice_force_N, dt)` | `slice_force_N` 为 `nSlices x 3` 的 `[Fx,Fy,Fz]`，单位 N |
| 运动映射 | `ancf_slice_motion(state)` | 直接产生 `time_s/slice_id/s_ref_m/x/y/z/v/a` 字段 |
| 运动文件 | `ancf_write_slice_motion_csv(motion, filepath)` | 已采用临时文件写入后原子替换 |
| 载荷文件 | `ancf_read_slice_loads_csv(filepath, model)` | 载荷文件必须是每切片积分力 `force_*_N`，不是 N/m |
| 载荷映射 | `ancf_external_load(state, slice_force_N)` | 使用既有 `H3' * Fslice`，不重复映射 |
| 回滚基础 | `ancf_save_checkpoint` / `ancf_load_checkpoint` | 后续强耦合可在同一步保存/恢复 |
| 结构后处理 | `state.output` / `ancf_postprocess` | 当前已有位移、曲率、Green 应变、材料轴力和当前投影张力 |

当前 `ancf_advance_step` 使用稠密有效刚度矩阵求解；稀疏化属于任务 0 的独立硬化工作，不在本次固定圆柱启动中改动。

## 3. 环境检查

| 依赖 | 检查结果 | 影响 |
|---|---|---|
| OpenFOAM | WSL2 `/opt/openfoam10`，可调用 `blockMesh`、`icoFoam`、`pimpleFoam`、`wmake` | 可运行固定圆柱；Windows 主机侧没有直接 PATH 命令 |
| OpenFOAM 版本 | 10 | 案例文件按 OpenFOAM Foundation v10 写，不混入 v11/v12 语法 |
| 编译器 | WSL2 GCC 11.4.0 | 预留给后续自定义读写/动态网格组件 |
| MATLAB | `D:\Matlab\bin\matlab.exe` | 可运行阶段一回归和后续 ANCF 回放 |
| Python | WSL2 Python 3.10.12、NumPy 1.21.5、Matplotlib 3.5.1 | 可完成力时程、频谱和图形后处理 |
| ParaView | WSL2 `/opt/paraviewopenfoam510/bin/pvpython`，`paraFoam` 可调用 | 可生成尾涡瞬态图；若无图形显示则导出离线图 |
| Git | Windows 主机可调用 | 可追踪重构模块与案例变更 |

缺失或待确认项：主机 Windows 不直接提供 OpenFOAM 命令；必须通过 WSL2 运行并记录发行版、挂载路径和命令。当前没有发现阻塞固定圆柱的依赖缺口。

## 4. 任务 1 固定圆柱实施方案

首个基准采用二维、不可压、层流、固定圆柱绕流：

```text
D = 1 m                    圆柱直径
U_inf = 1 m/s              来流速度，+x
rho = 1000 kg/m^3          参考密度，用于把运动压力换成 N
nu = 0.01 m^2/s            运动黏度
Re = U_inf*D/nu = 100      直径定义的 Reynolds 数
L_z = 1 m                  有限计算厚度；前后面为 empty
```

求解器固定为 OpenFOAM Foundation v10 的 `icoFoam`，时间离散使用一阶 Euler，空间对流项先用 `Gauss linear`，PISO 两次压力修正。网格采用八扇区圆柱贴体块网格，圆柱壁半径 `0.5D`，第一外环半径 `0.8D`，外边界约为上游 `5D`、下游 `10D`、横向 `5D`。首个中等网格使用单位展向厚度和 `empty` 前后边界。

首轮时间步固定为 `dt=0.0025D/U`，对应实际运行中的最大 CFL 约为 `0.185`；首个可复现实测运行计算到 `t=30D/U`，后处理窗口取 `15D/U≤t≤30D/U`，再由升力主频计算 `St=fD/U`。初始场使用 `setFields` 在尾流近场施加记录过的微小横向速度种子，以避免完全对称离散状态长期保持零升力；该种子不是物理入口条件。

力输出同时保存：

1. `forces`：圆柱壁压力力、黏性力和力矩；
2. `forceCoeffs`：`Cd`、`Cl` 和绕 z 轴力矩系数；
3. WSL 日志：残差、时间步信息和 Courant 数；
4. 后处理 CSV/PNG：力时程、升力频谱、尾流速度/涡量图。

二维力的闭合约定是：OpenFOAM 在本案例中对 `L_z=1 m` 的有限厚度网格积分，输出为该有限厚度下的总力 N；由于 `L_z=1 m`，数值上等于单位展向力 `f_2D [N/m]`。向 ANCF 传递实际切片时只允许做一次

```text
F_slice [N] = f_2D [N/m] * l_slice [m]
```

本固定圆柱案例本身不把这个 N 再乘一次长度；后续文件式耦合转换器才负责根据切片代表长度完成一次换算。

## 5. 当前边界与停止条件

本次启动只建立和验证固定圆柱，不宣称规定运动、自由耦合或整根柔性立管 VIV 已完成。若首轮固定圆柱的 `Cd_mean`、`Cl` 主频或网格质量明显异常，下一步先修 CFD 案例，不进入耦合。
