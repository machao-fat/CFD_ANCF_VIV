# HH06 Adapter Displacement Read Path Fix Report

## 结论

隔离 OpenFOAM 10 adapter 已完成最小实现和编译资格检查。生产 adapter、原始 `slice0000`、ANCF kernel、qualified worker、SHM1、`fvSchemes`、`fvSolution`、湍流模型和 `dynamicMeshDict` 均未修改。

最终分类：`PASS_HH06_NONZERO_ALE_ONE_WINDOW_QUALIFICATION`

下一阶段仅授权：`HH06_BOUNDED_MULTIWINDOW_ALE_QUALIFICATION`。本轮没有运行 50-window 或 0.2 s production FSI。

## 修改范围

唯一修改的 adapter 生产源文件是隔离副本：

`D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\hh06_adapter_displacement_read_path_fix_v1\adapter_source\Adapter.C`

最终 SHA256：

`710F45FBA682442CBEC979D6993A24B2C530B0E592B62C18041D429CA4DD6301`

实现内容：

1. `initialize()`：`precice_->initialize()` 后执行 `readCouplingData(0.0)`，再进入首个 checkpoint/Fluid solve。
2. `execute()`：`write -> advance -> conditional rollback/checkpoint -> readCouplingData(maxDt) -> timestep adjustment`。
3. point-vector checkpoint 使用完整 field clone/reset，保留 `pointDisplacement` 的 boundary state。
4. rollback 后显式恢复 checkpoint `oldPoints`，拒绝 trial mesh history 泄漏到 retry。
5. 首窗口 checkpoint 时 `meshPhi` 尚未注册；rollback 创建该场后强制恢复为物理等价的零 flux。
6. 诊断增加实际 `min/max cell volume`、`max non-orthogonality`、`max skewness`。

辅助脚本仅用于隔离构建和一次性资格运行：

- `build_qualification_adapter.sh`
- `run_one_window_qualification.sh`

隔离 case 的 `precice-config.xml` 只改变 socket exchange directory；participant、mesh、mapping、数据名、parallel-implicit、时间窗和松弛设置未改变。

## 编译 provenance

- OpenFOAM：10
- `WM_OPTIONS`：`linux64GccDPInt32Opt`
- compiler：g++ 11.4.0
- preCICE：3.4.1
- build flags：`-DADAPTER_DEBUG_MODE`
- binary：`/home/machao/OpenFOAM/hh06_adapter_displacement_read_path_fix_v1/qualification_lib_attempt2b/libpreciceAdapterFunctionObject.so`
- binary SHA256：`8c2c0fda85dc7ed452eb144b03a92ac9bf739e62ee8369baf489b3439cfdf458`
- size：1,788,952 bytes
- `ldd -r`：无 missing library 或 undefined symbol

第一次 attempt 使用的 read-path-only binary SHA256 为 `26cf3057...df3ca`，其全部运行证据保存在 `artifacts/attempt1/`。它暴露出 `oldPoints/meshPhi/pointDisplacement` rollback 不完整，因此没有被当作 PASS。

实现过程中有一次编译 API 检查失败：OpenFOAM 10 的 `fvMesh::phiRef()` 为 private。失败日志保存在 `artifacts/build_attempt2.*`。随后改用公开 `phi()` 的受控 `const_cast`；成功构建日志为 `artifacts/build_attempt2b.*`。

## 实际加载证明

运行时 `/proc/<pimpleFoam>/maps` 捕获：

- PID：665502
- executable：`/opt/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam`
- loaded library：`/home/machao/OpenFOAM/hh06_adapter_displacement_read_path_fix_v1/qualification_lib_attempt2b/libpreciceAdapterFunctionObject.so`

同时，运行日志出现本补丁独有的 `INITIAL_READ_*`、`READ_DATA_AFTER_CHECKPOINT_ACTIONS` 事件，排除了误加载生产 adapter。

## 顺序验证

初始化事件顺序：

`INITIAL_READ_ENTRY -> READ_DATA_ENTRY -> READ_DATA_EXIT -> INITIAL_READ_EXIT -> CHECKPOINT_WRITE`

rollback/retry 顺序：

`PRE_ROLLBACK_TRIAL -> CHECKPOINT_READ_AFTER_RESTORE -> READ_DATA_AFTER_CHECKPOINT_ACTIONS -> READ_DATA_ENTRY -> READ_DATA_EXIT -> next pimpleFoam mesh motion`

该顺序与冻结设计一致。`FSI::Displacement::read()` 通过两次 `READ_DATA_FIELD_USER_APPLIED` 得到运行时证明。

## 保护检查

- production adapter SHA256 仍为 `26ad8529822f96ca8ddfb3370f85257b0d19b56958538d6073cf8af897aac572`。
- qualified SHM1 worker SHA256 仍为 `69f045eb7f4576e5178d10711f0f265d7458282a7a4ecbcb860a913ada45beef`。
- 原始 `slice0000` 仍只有 CFD restart 数值目录 `30`。
- 隔离 case 也没有生成新的 OpenFOAM 数值时间目录。
- 原始与隔离副本的 `fvSchemes`、`fvSolution`、`dynamicMeshDict` SHA256 分别一致。

## 限制

本次 `1e-4 m` transverse offset 是 diagnostic-only，只用于激发 ALE 路径；它没有修改 ANCF `q/qdot/qddot`，也不是 HH06 物理结果。

