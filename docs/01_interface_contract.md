# CFD–耦合器–结构模块接口合同（v0.1）

## 1. 目的与冻结原则

本合同定义三个模块之间交换的物理量，不绑定 ANCF 的内部语言或 OpenFOAM 的具体字典实现：

```text
OpenFOAM slices  <->  Coupler  <->  ANCF or Linear-EB adapter
```

接口只有在以下四项同时变化时才升级主版本：自由度物理意义、坐标系、单位、载荷共轭关系。新增可选字段只升级次版本。任何模块都不得根据列位置或文件名猜测单位和符号。

当前状态为 `schema_version = "0.1.0"`。ANCF 源码审查后冻结为 `1.0.0`。

## 2. 全局约定

### 2.1 坐标系

- 右手全局系 `G`；
- `+z`：沿未变形立管从底端到顶端；
- `+x`：in-line，正来流方向；
- `+y`：cross-flow，满足 `e_x × e_y = e_z`；
- 参考弧长 `s=0` 在底端，`s=L` 在顶端；
- 所有切片主线中均使用与全局 `x-y` 平行的固定平面，不随局部切线旋转。

### 2.2 单位

只允许 SI：`m, s, kg, N, Pa, rad`。角度数值用 `rad`。CSV 单元格中只存数值，单位写在列名或 metadata 中，不写成 `0.5 m`。

### 2.3 正负号

- `fx_N > 0` 表示流体对结构沿 `+x` 的力；
- `fy_N > 0` 表示流体对结构沿 `+y` 的力；
- OpenFOAM 原始输出的符号转换只在 CFD adapter 中进行一次；
- 用静止圆柱正来流算例验收：时间平均 `fx_N` 必须为正，时间平均 `fy_N` 接近零。

### 2.4 数值精度和缺失值

- 文件输出至少 16 位有效十进制数字；
- 禁止用空字符串、`NaN` 或 `Inf` 表示合法状态；
- 不可用字段在 metadata 的 `optional_fields_missing` 中声明；
- 任一必填值非有限数时，该时间步不得提交。

## 3. 运行目录和原子提交

建议每个 case 使用：

```text
cases/<case_id>/
  case.json
  coupling/
    static/
      structure_nodes.csv
      slices.csv
      H_motion.mtx
      mapping.json
    step_00000000/
      request.json
      slice_motion.csv
      slice_loads.csv
      structure_state.csv
      diagnostics.json
      COMMITTED
```

写文件时先写同目录临时名 `<name>.tmp`，关闭并校验后原子重命名为正式文件；最后创建 `COMMITTED`。读方只读取含 `COMMITTED` 的步目录。失败步保留 `FAILED.json`，不得伪装为已提交。

原型期使用 UTF-8 CSV + JSON + Matrix Market，以便 MATLAB/Python/C++/Fortran 都能读取。生产期可替换为 HDF5、socket 或共享库，但字段、坐标、单位、时间戳和 `H/H^T` 关系必须保持不变。

## 4. 静态文件

### 4.1 `case.json`

必填键：

| 键 | 类型 | 含义 |
|---|---|---|
| `schema_version` | string | 当前为 `0.1.0` |
| `case_id` | string | 只含字母、数字、下划线、短横线 |
| `coordinate_system` | string | 固定为 `G_X_IL_Y_CF_Z_BOTTOM_TO_TOP` |
| `units` | string | 固定为 `SI` |
| `structure_model` | enum | `ANCF` 或 `LINEAR_EB` |
| `coupling_scheme` | enum | `CSS_LOOSE` 或 `FIXED_POINT_AITKEN` |
| `dt_coupling_s` | number | 耦合步长 |
| `t_start_s`, `t_end_s` | number | 模拟时间范围 |
| `n_slices` | integer | CFD 切片数 |
| `openfoam_variant` | string | 如 `foundation` |
| `openfoam_version` | string | 固定版本/补丁标识 |
| `git_commit` | string | 本项目提交哈希；未使用 Git 时填 `UNTRACKED` 并警告 |

建议首个稳定环境采用 OpenFOAM Foundation 的已打补丁版本。2026 年 7 月最新为 [v14](https://openfoam.org/version/14/)，但它刚发布；为降低接口变化风险，阶段二可先固定经过回归测试的 Foundation v13 补丁版，完成基准后再评估 v14。不能把 VIVdatashare 的 OpenFOAM-8 case 直接标为兼容。

### 4.2 `structure_nodes.csv`

该文件描述结构参考网格，不描述 ANCF 内部所有自由度。

| 列 | 类型 | 单位 | 必填 | 含义 |
|---|---|---|---|---|
| `node_id` | int | - | 是 | 从 0 连续编号 |
| `s_ref_m` | float | m | 是 | 参考弧长，严格递增 |
| `x_ref_m` | float | m | 是 | 参考坐标 |
| `y_ref_m` | float | m | 是 | 参考坐标 |
| `z_ref_m` | float | m | 是 | 参考坐标 |
| `boundary_tag` | string | - | 是 | `BOTTOM`, `INTERIOR`, `TOP` |
| `element_left` | int | - | 否 | 左侧单元 id |
| `element_right` | int | - | 否 | 右侧单元 id |

### 4.3 `slices.csv`

| 列 | 类型 | 单位 | 必填 | 含义 |
|---|---|---|---|---|
| `slice_id` | int | - | 是 | 从 0 连续编号 |
| `s_ref_m` | float | m | 是 | 切片参考位置，严格递增 |
| `axial_weight_m` | float | m | 是 | 将单位长度合力转为集中力的轴向求积权重 |
| `extrusion_thickness_m` | float | m | 是 | OpenFOAM 单层挤出厚度 |
| `inflow_x_mps` | float | m/s | 是 | 该切片入口 IL 速度 |
| `inflow_y_mps` | float | m/s | 是 | 主线应为 0 |
| `active_cfd` | bool | - | 是 | 是否实际运行 CFD |
| `fluid_case_relpath` | string | - | 是 | 相对 case 根目录的 OpenFOAM 路径 |

必须满足 `sum(axial_weight_m)` 等于有水动力积分区间的长度，容差 `1e-12 L`。静水段若不运行 CFD，`active_cfd=false`，并明确其水动力被设为零还是由其他附加质量/阻尼模型补偿；两者不能混用。

### 4.4 `H_motion.mtx` 与 `mapping.json`

`H_motion.mtx` 使用 Matrix Market coordinate real general 格式。行按

```text
[slice0_x, slice0_y, slice1_x, slice1_y, ...]
```

排列；列严格按结构 adapter 的 `coupling_dof_order` 排列。

`mapping.json` 必填：

- `matrix_file`；
- `rows`, `cols`, `nnz`；
- `row_order`；
- `coupling_dof_order`；
- `structure_internal_dof_description`；
- `matrix_checksum_sha256`；
- `motion_relation = "x_slice = H q_structure"`；
- `load_relation = "F_structure = transpose(H) F_slice"`；
- `weights_in_force_vector = true`。

若 ANCF 内部自由度含位置和斜率，`coupling_dof_order` 必须逐项列出，例如 `node_0_r_x`, `node_0_r_y`, `node_0_r_z`, `node_0_slope_x`, ...。不得只写“12 DOF element”。

## 5. 动态交换文件

### 5.1 `request.json`

| 键 | 类型 | 含义 |
|---|---|---|
| `step` | int | 时间步编号，从 0 开始 |
| `coupling_iteration` | int | 松耦合固定为 0，强耦合从 0 开始 |
| `time_n_s` | float | 步起点 |
| `time_np1_s` | float | 步终点 |
| `dt_coupling_s` | float | 必须等于两时间戳之差 |
| `state_time_level` | enum | `PREDICTED_NP1`, `CONVERGED_NP1` |
| `force_time_level` | enum | `ENDPOINT_NP1`, `MIDPOINT`, `TIME_AVERAGED_OVER_STEP` |
| `restart_from_step` | int/null | 重启来源 |

### 5.2 `slice_motion.csv`：Coupler → CFD

每个 active slice 每个耦合迭代恰好一行：

| 列 | 单位 | 必填 | 含义 |
|---|---|---|---|
| `schema_version` | - | 是 | `0.1.0` |
| `step` | - | 是 | 与 request 一致 |
| `coupling_iteration` | - | 是 | 与 request 一致 |
| `time_s` | s | 是 | 运动状态时间戳 |
| `slice_id` | - | 是 | 与 `slices.csv` 对应 |
| `center_x_m` | m | 是 | 圆心全局 x |
| `center_y_m` | m | 是 | 圆心全局 y |
| `center_z_m` | m | 是 | 参考/当前 z；二维 CFD 仅记录不使用 |
| `velocity_x_mps` | m/s | 是 | 圆心速度 |
| `velocity_y_mps` | m/s | 是 | 圆心速度 |
| `velocity_z_mps` | m/s | 是 | 记录；二维 CFD 主线不使用 |
| `acceleration_x_mps2` | m/s2 | 建议 | 强耦合/高阶时间插值可用 |
| `acceleration_y_mps2` | m/s2 | 建议 | 同上 |

插值到流体子步时必须记录算法，如线性、Hermite 或结构预测器。禁止在一个流体子步中把位移取 `t_np1` 而速度取 `t_n`。

### 5.3 `slice_loads.csv`：CFD → Coupler

| 列 | 单位 | 必填 | 含义 |
|---|---|---|---|
| `schema_version` | - | 是 | `0.1.0` |
| `step` | - | 是 | 时间步 |
| `coupling_iteration` | - | 是 | 耦合迭代 |
| `time_s` | s | 是 | 与 `force_time_level` 一致 |
| `slice_id` | - | 是 | 切片 id |
| `force_x_N` | N | 是 | **已乘轴向权重**的流体对结构 IL 合力 |
| `force_y_N` | N | 是 | **已乘轴向权重**的流体对结构 CF 合力 |
| `force_z_N` | N | 是 | 主线固定为 0 |
| `line_force_x_Npm` | N/m | 是 | 除以挤出厚度后的单位长度合力，便于审计 |
| `line_force_y_Npm` | N/m | 是 | 同上 |
| `pressure_force_x_N` | N | 建议 | 压力贡献，已乘轴向权重 |
| `pressure_force_y_N` | N | 建议 | 压力贡献，已乘轴向权重 |
| `viscous_force_x_N` | N | 建议 | 黏性贡献 |
| `viscous_force_y_N` | N | 建议 | 黏性贡献 |
| `raw_openfoam_fx_N` | N | 建议 | 未除挤出厚度、未乘轴向权重的原始值 |
| `raw_openfoam_fy_N` | N | 建议 | 同上 |
| `cfd_converged` | bool | - | 是 | 本步 CFD 收敛标志 |

必须满足

```text
force_x_N = line_force_x_Npm * axial_weight_m
force_y_N = line_force_y_Npm * axial_weight_m
```

并在 `1e-10` 相对容差内通过。`F_slice` 就是按 `force_x_N, force_y_N` 排列的向量；Coupler 只能用 `H^T F_slice` 组装结构广义力，不得再次乘轴向权重。

### 5.4 `structure_state.csv`：Structure → Coupler/Results

每个结构中心线节点一行：

| 列 | 单位 | 必填 | 含义 |
|---|---|---|---|
| `step`, `coupling_iteration`, `time_s` | -, -, s | 是 | 状态标识 |
| `node_id`, `s_ref_m` | -, m | 是 | 节点标识 |
| `x_m`, `y_m`, `z_m` | m | 是 | 当前中心线位置 |
| `vx_mps`, `vy_mps`, `vz_mps` | m/s | 是 | 当前速度 |
| `ax_mps2`, `ay_mps2`, `az_mps2` | m/s2 | 是 | 当前加速度 |
| `curvature_x_1pm`, `curvature_y_1pm`, `curvature_mag_1pm` | 1/m | 是 | 曲率 |
| `axial_strain` | - | ANCF 必填 | 轴向应变 |
| `effective_tension_N` | N | ANCF 必填 | 采用明确定义恢复的有效轴力 |
| `slope_x`, `slope_y`, `slope_z` | - | ANCF 必填 | 中心线斜率 |

线性梁也应输出相同位置/曲率列；其 `effective_tension_N` 可输出预设 `T0(s)`，同时在 metadata 中标记 `tension_is_prescribed=true`。

### 5.5 `diagnostics.json`

至少包含：

- `mapping_virtual_work_relative_error`；
- `mapping_power_relative_error`；
- `resultant_force_error_N`；
- `resultant_moment_error_Nm`；
- `cfd_max_courant`；
- `cfd_initial_residuals`, `cfd_final_residuals`；
- `structure_newton_iterations`；
- `structure_residual_norm`；
- `coupling_displacement_residual`；
- `coupling_force_residual`；
- `aitken_relaxation`；
- `wall_clock_cfd_s`, `wall_clock_structure_s`, `wall_clock_coupler_s`；
- `warnings` 数组。

## 6. 模块 API 语义

即使原型使用文件，三个 adapter 也应提供等价函数语义：

```text
initialize(case_metadata) -> capabilities
advance_or_solve(time_n, time_np1, input_state, iteration) -> output_state
checkpoint(step) -> checkpoint_id
restore(checkpoint_id)
finalize()
```

### 6.1 CFD adapter

输入：`slice_motion`、入口速度和时间区间。输出：`slice_loads`、CFD 收敛信息。一个调用只能推进到指定终点，不能擅自提交下一步。

### 6.2 Coupler

负责：构造/读取 `H`、运动映射、转置载荷映射、时间插值、耦合迭代、Aitken、原子提交和全部守恒诊断。Coupler 不计算结构内力，也不修改 CFD 壁面应力。

### 6.3 Structure adapter

输入：按内部自由度顺序的 `F_structure` 和时间区间。输出：`q, qdot, qddot`、中心线状态、曲率、轴力和非线性迭代信息。ANCF 与线性梁 adapter 必须实现相同外部语义。

## 7. 时间推进合同

结构为主时钟。推荐耦合步长 `dt_coupling` 与结构步长相同；CFD 可用整数个子步，必须满足

```text
time_np1 - time_n = n_fluid_substeps * dt_fluid
```

容差为 `100 * machine_epsilon * max(1, |time_np1|)`。非整数比必须显式使用最后一个截断子步并记录，禁止用累计浮点误差越过耦合时刻。

松耦合顺序固定为：结构预测 → CFD → `H^T` 载荷 → 结构校正。强耦合在同一 `time_np1` 内重复该过程；每次迭代前 CFD 和结构都从 `t_n` 的已提交 checkpoint 恢复，不能在前一迭代结果上继续多走一个时间步。

## 8. 必须通过的接口测试

| 测试 | 输入 | 通过标准 |
|---|---|---|
| Schema round-trip | 写入再读取全部静态/动态文件 | 字段、精度、顺序和 checksum 一致 |
| 坐标正方向 | 静止圆柱、`+x` 来流 | 平均 `force_x_N > 0`，平均 `force_y_N` 近零 |
| 刚体平移 | 结构全部节点平移同一向量 | 所有切片圆心平移相同 |
| 随机虚功 | 随机 `q, delta_q, F_slice` | 相对误差 `<1e-12` |
| 运行时功率 | 任意真实耦合步 | 相对误差 `<1e-8` 或说明文件精度瓶颈 |
| 轴向权重 | 常线载荷 | 结构总合力等于线载荷乘积分长度 |
| 重启一致性 | 连续运行与 checkpoint 重启 | 状态差在时间积分容差内 |
| 双结构公平性 | 同一 `slice_loads` 回放给两 adapter | 输入文件 checksum 完全相同 |
| 失败步隔离 | 人为制造 CFD 不收敛 | 无 `COMMITTED`，后续不读取该步 |

## 9. 仍待 ANCF 程序确认的接口项

在收到程序前，以下内容保持 `TBD`：内部自由度顺序、约束形式、能否返回轴力/曲率、结构步长是否可外部控制、是否支持 rollback/checkpoint、是否可作为共享库调用。若程序只能一次性读完整载荷时序，先实现“载荷回放”而不是假装它已支持双向耦合。
