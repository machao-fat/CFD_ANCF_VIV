# 阶段四A：多切片协议、力学映射与守恒验证报告

## 1. 结论与范围

本报告记录一个独立的 Stage-4A Draft 1（`schema_version=0.2.0`）多切片 schema、二维力换算、ANCF 切片 H 插值、H^T 广义力映射、虚功审计和合成协议测试实现。

实现位于 `src/coupling/multi_slice_mapping`，没有修改公共 `src/coupling/file_exchange`、阶段三证据、ANCF 内力/应变/刚度/Newton 核心、OpenFOAM 生产版本、driver 或 checkpoint 目录。实现与测试只覆盖本子任务的纯函数和文件验证范围，不构成整根柔性立管、多进程 CFD、跨进程时间屏障、原子 checkpoint 或真实多切片 VIV 长算例的物理验证。

正式 Gate 4A 仍由 Sol 主Agent 复核并决定。

## 2. 坐标系与旋转审计

全局右手坐标系 G 采用：全局 X 为基准来流方向，Y 为横流方向，Z 为立管轴向；参考中心线从底端沿 +Z 递增，`0 <= s_ref_m <= reference_length_m`。当前直立基准中固定局部基为

```text
e_streamwise = (1, 0, 0)
e_crossflow  = (0, 1, 0)
e_axial      = (0, 0, 1)
R_GL = [e_streamwise, e_crossflow, e_axial] = I
```

代码仍显式调用 `local_to_global()` 和 `global_to_local()`，后者使用 `R_GL^T`。`R_GL` 的列向量必须正交归一，且行列式在 `1e-12` 相对尺度内接近 `+1`；不允许通过当前 `R_GL=I` 的偶然相等省略转换。Draft 1 不实现动态局部坐标，也不把 CFD 力矩映射到 ANCF 广义力。

## 3. 数据 schema、字段与单位

### 3.1 静态切片表

`SliceManifest` 的核心字段为：

| 字段 | 单位/约束 |
|---|---|
| `schema_version` | 字符串，严格为 `0.2.0`；旧 `0.1.0` 明确拒绝 |
| `case_id` | 非空字符串 |
| `reference_length_m` | m，参考中心线长度，必须 > 0 |
| `represented_length_m` | m，显式配置的切片代表区段长度，必须 > 0 |
| `R_GL` | 无量纲 3×3 固定局部基到全局基矩阵 |
| `slices` | `slice_id`、`s_ref_m`、`slice_length_m` 列表 |
| `config_sha256` | 配置规范化 JSON 的 SHA-256，小写 64 位十六进制 |
| `slice_manifest_sha256` | 静态切片表规范化 JSON 的 SHA-256，小写 64 位十六进制 |

切片表读取后按 `slice_id` 恢复升序；合法集合严格为 `0..N-1`。缺失、重复、意外 ID、重复 `s_ref_m`、非有限坐标、非正代表长度和 `sum(slice_length_m)` 不匹配 `represented_length_m` 均 fail-closed。`represented_length_m` 不被强制等于整根 `reference_length_m`，因此显式配置局部区段是允许的。

### 3.2 运动 payload

`MotionRecord` 保留 Draft 1 的一行字段：

`schema_version, case_id, step, coupling_iteration, time_s, slice_id, s_ref_m, slice_length_m, x_ref_m, y_ref_m, z_ref_m, ux_m, uy_m, uz_m, x_m, y_m, z_m, vx_mps, vy_mps, vz_mps, ax_mps2, ay_mps2, az_mps2, status`。

`x_m/y_m/z_m` 强制按

```text
x_m = x_ref_m + ux_m
y_m = y_ref_m + uy_m
z_m = z_ref_m + uz_m
```

校验；速度为 m/s，加速度为 m/s²，`status=complete`，`coupling_iteration=0`。所有数值字段必须有限，`step` 非负，`time_s` 非负。

### 3.3 载荷 payload

`LoadRecord` 保留三个可审计力层次及局部投影字段：

`schema_version, case_id, step, coupling_iteration, time_s, slice_id, s_ref_m, slice_length_m, unit_span_m, force_representation, openfoam_force_x_N/y_N/z_N, force_2d_x_Npm/y_Npm/z_Npm, force_x_N/y_N/z_N, force_local_streamwise_N, force_local_crossflow_N, force_local_axial_N, cfd_time_step_s, status`。

单位分别为：OpenFOAM 总力 N；二维单位跨距力 N/m；结构切片积分力 N；`unit_span_m`、`slice_length_m` 为 m；`cfd_time_step_s` 为 s。`force_representation` 严格为 `integrated_slice_force_N`，`status=complete`。

### 3.4 ready/consumed marker

`ReadyMarker` 严格包含：

`schema_version, marker_type, payload_kind, case_id, slice_id, step, coupling_iteration, time_s, payload, row_count, payload_sha256, config_sha256, slice_manifest_sha256`。

`marker_type=ready`、`payload_kind` 为 `motion` 或 `load`、`row_count=1`。`ConsumedMarker` 在此基础上包含 `marker_type=consumed` 和非空 `consumer`，不包含 `row_count`。marker 对身份、step/time/iteration、三个 SHA-256、payload 原始字节和文件名进行校验；`create_consumed_marker()` 要求再次提供 payload 路径并重新计算 payload SHA-256。

模块提供 `atomic_write_csv()` 与 `atomic_write_json()`，均使用同卷临时文件、flush、fsync 和 `os.replace`。本任务不实现多进程调度器、等待器或 checkpoint 调度。

## 4. 二维力换算与 Δs 审计

唯一的力换算函数 `convert_openfoam_force()` 执行：

```text
f_i^(2D) = F_i^(OpenFOAM) / unit_span_m       [N/m]
F_i      = f_i^(2D) * slice_length_m          [N]
         = F_i^(OpenFOAM) * slice_length_m / unit_span_m
```

`F_i` 是唯一允许进入 H^T 映射的全局积分切片力。`map_integrated_slice_forces()` 只接受/解释已经积分的 N，不再次乘 `slice_length_m`，因此 `slice_length_m` 只出现于换算阶段一次。`LoadRecord` 同时检查 OpenFOAM 总力、二维力、积分力三层之间的相对一致性，阈值为 `1e-12`。

局部力由 `F_local = R_GL^T F_global` 显式得到；当前 `R_GL=I` 只使数值相等，不改变代码路径。

## 5. ANCF H 插值与 H^T 映射

现有 MATLAB ANCF 实现已只读确认每节点 6 个自由度，排列为：

```text
[r_x, r_y, r_z, r_sx, r_sy, r_sz]
```

参考模块 `ancf_hermite_H()` 使用已确认的三次 Hermite 形函数 `[S1,S2,S3,S4]`，在所属单元的实际局部坐标中形成 3×ndof 矩阵：

```text
H_i = [S1 I3, S2 I3, S3 I3, S4 I3]
r_i    = H_i q
v_i    = H_i qdot
a_i    = H_i qddot
delta_r_i = H_i delta_q
```

`build_H_for_manifest()` 根据 `s_ref_m` 和非均匀 `mesh_nodes` 定位所属单元，而不是按最近节点选取。实现支持节点重合、单元内部位置、非均匀网格以及同一单元中的多个切片；`build_H_for_manifest()` 返回以 `slice_id` 为键的矩阵字典，输入行顺序不参与身份判断。

广义力为：

```text
Q = sum_i H_i^T F_i
```

每个 `F_i` 必须是已乘过 `slice_length_m` 的积分全局力 N，H^T 内部不再做长度积分。返回值同时包含总 `Q`、各切片 `H_i^T F_i`、换算审计和虚功审计。

## 6. 虚功守恒

对任意有限 `delta_q`，审计计算：

```text
W_slice        = sum_i F_i dot (H_i delta_q)
W_generalized  = delta_q^T Q
error_abs      = |W_slice - W_generalized|
error_rel      = error_abs / max(1, |W_slice|, |W_generalized|)
```

`VirtualWorkAudit` 输出两侧虚功、绝对误差、相对误差、随机种子、切片数、结构自由度数，以及每个 `slice_id`、`s_ref_m` 和 `slice_length_m`。`assert_virtual_work()` 使用未放宽的 `1e-12` 相对阈值。

## 7. 合成测试矩阵

测试文件为 `tests/multi_slice_mapping/test_mapping.py`，独立 runner 为 `tests/multi_slice_mapping/run_tests.py`。本次执行的 38 项全部通过，覆盖用户要求的 30 类场景：

| 验收项 | 覆盖测试 | 结果 |
|---:|---|:---:|
| 1 | `test_single_slice_compatibility` | PASS |
| 2 | `test_two_uniform_slices` | PASS |
| 3 | `test_five_uniform_slices` | PASS |
| 4 | `test_nonuniform_slice_lengths` | PASS |
| 5 | `test_end_half_slices` | PASS |
| 6 | `test_slice_between_ancf_nodes_and_multiple_in_one_element`, `test_node_coincidence_on_nonuniform_mesh` | PASS |
| 7 | `test_input_rows_are_restored_by_slice_id` | PASS |
| 8 | `test_missing_slice_rejected` | PASS |
| 9 | `test_duplicate_slice_rejected`, `test_duplicate_slice_id_manifest_rejected` | PASS |
| 10 | `test_unexpected_slice_rejected` | PASS |
| 11 | `test_duplicate_s_ref_rejected` | PASS |
| 12–13 | `test_nan_rejected`, `test_inf_rejected` | PASS |
| 14–16 | `test_step_inconsistency_rejected`, `test_time_inconsistency_rejected`, `test_nonzero_coupling_iteration_rejected` | PASS |
| 17–18 | `test_s_ref_tamper_rejected`, `test_slice_length_tamper_rejected` | PASS |
| 19–21 | `test_payload_tamper_after_ready_rejected`, `test_config_sha256_wrong_rejected`, `test_slice_manifest_sha256_wrong_rejected` | PASS |
| 22 | `test_delta_s_is_applied_once` | PASS |
| 23–24 | `test_uniform_constant_force_total`, `test_antisymmetric_slice_forces_cancel` | PASS |
| 25–26 | `test_random_virtual_work_conservation`, `test_multiple_random_seeds_virtual_work` | PASS |
| 27 | `test_local_global_local_roundtrip` | PASS |
| 28 | `test_nonunit_openfoam_span` | PASS |
| 29 | `test_represented_length_can_be_a_configured_subsection` | PASS |
| 30 | `test_old_schema_is_explicitly_rejected` | PASS |

额外覆盖了同一 H 的 `r/v/a` 插值、ANCF 状态生成、marker roundtrip、canonical JSON 键序独立性、旋转矩阵正定性和 H/力集合缺失拒绝。

## 8. 定量结果

机器可读结果位于 `results/05_multi_slice_mapping_tests/mapping_test_summary.json`：

| 指标 | 结果 |
|---|---:|
| 本任务测试 | 38 run / 38 passed / 0 failed |
| 最大合成力换算相对误差 | `0.0` |
| 最大虚功绝对误差 | `6.661338147750939e-15 J` |
| 最大虚功相对误差 | `6.661338147750939e-15` |
| 虚功随机种子 | `17, 0, 1, 5, 19, 42` |
| 随机虚功结构自由度 | 24 |
| 随机虚功切片数 | 5、4 |
| 按 slice_id 置换 | PASS |
| 缺失/重复/意外 slice_id 拒绝 | PASS |
| NaN/Inf 拒绝 | PASS |
| payload 篡改/hash 拒绝 | PASS |
| Δs 只乘一次 | PASS |
| 旧 0.1.0 拒绝 | PASS |

旧协议回归：

| 命令范围 | 结果 |
|---|---:|
| `python -m unittest discover -s tests/coupling_io -p "test*.py" -v` | 6/6 PASS |
| `python -m unittest discover -s tests/online_motion_adapter -p "test*.py" -v` | 9/9 PASS |
| `python -m unittest discover -s tests -p "test*.py" -v` | 99 run / 98 passed / 1 failed（并行任务 `tests/multi_slice_driver`，不在本任务授权范围） |
| `python -m compileall -q src tests` | PASS |

全项目回归的唯一失败为 `multi_slice_driver.test_orchestration.MultiSliceOrchestrationTests.test_state_machine_two_slice_success_and_atomic_commit`：该测试要求日志状态为字符串 `PREDICTED`，实际并行任务代码输出 `SchedulerState.PREDICTED`。本任务没有读取后修改该目录，也没有将该失败伪装为本任务通过。

## 9. 未解决问题与边界

1. 本实现未启动 OpenFOAM，也没有宣称真实多切片 CFD 长算例或整根柔性立管 VIV 已验证。
2. 本实现不负责多 OpenFOAM 进程调度、跨进程时间屏障、checkpoint 调度、driver、Aitken 强耦合或真实 restart。
3. Draft 1 的全局/局部基当前固定为直立基准；动态局部坐标、曲线立管和平台运动不在范围内。
4. 本实现提供 marker/payload 对象、哈希验证和原子写工具，但未把它们接入公共 file-exchange 或调度器。
5. `docs/05_multi_slice_contract.md` 未创建、未覆盖、未修改；需要由 Sol 主Agent 按本报告复核后冻结正式公共协议。

## 10. 请求 Sol 决定的事项

接口层面无阻塞请求；请 Sol 主Agent 复核：

- `SliceManifest` 中 `reference_length_m`、`represented_length_m`、`R_GL` 和 `config` 的正式 JSON 命名是否与其公共 Draft 1 文档一致；
- 是否将本模块的 marker 原子写/读取入口接入公共 file-exchange（如需修改公共代码，应另行形成建议补丁，不由本任务自动应用）；
- 在检查共享工作区后决定 Gate 4A 的正式结论。
