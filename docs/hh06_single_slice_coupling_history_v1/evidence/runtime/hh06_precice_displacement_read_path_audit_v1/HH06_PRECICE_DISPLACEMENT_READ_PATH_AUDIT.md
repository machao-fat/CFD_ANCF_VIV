# HH06 PRECICE DISPLACEMENT READ PATH AUDIT

## 结论

本次审计分类：`DO_NOT_PASS_DISPLACEMENT_READ_PATH_NOT_CONNECTED`。

preCICE 确实收到并映射了 `Structure_0000` 的非零 `Displacement`，但在实际加载的 OpenFOAM adapter 生产执行路径中，没有调用 `Adapter::readCouplingData()`，因此没有执行 `precice_.readData(...)`，也没有执行 `FSI::Displacement::read(...)`。结果是 `pointDisplacement`/`cellDisplacement` 保持零，`displacementLaplacian` 没有非零输入，网格点和 `meshPhi` 不发生由结构位移驱动的变化。

本轮只运行了一个真实 `Fluid_0000` + `Structure_0000` 单窗口诊断；没有运行 50-window、production FSI，也没有修改原始 `slice0000`。

## 1. 执行边界与隔离

- 隔离审计目录：`D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\hh06_precice_displacement_read_path_audit_v1`
- 隔离 OpenFOAM case：`D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\hh06_precice_displacement_read_path_audit_v1\case`
- 原始 case：`/home/machao/OpenFOAM/coupling/singal_slice/slice0000`
- 原始 case 执行后仍只有数值目录 `30`；没有创建新的原始 case 时间目录。
- 运行边界：一个 `0.0002 s` coupling window，`parallel-implicit`，两次 fluid trial（一次 rollback/retry）。
- Structure 位移使用 `--diagnostic-only --diagnostic-offset-y 1e-4`，仅用于激活读路径，明确不是 HH06 物理结果；ANCF q/qdot/qddot 未被修改。
- fluid return code：`0`；participant return code：`0`；返回正常不等于位移路径通过。

## 2. 实际 adapter 身份

本次真实 fluid 进程通过隔离 `LD_LIBRARY_PATH` 首项加载：

`/home/machao/OpenFOAM/hh06_precice_displacement_read_path_audit_v1/diagnostic_lib/libpreciceAdapterFunctionObject.so`

- SHA256：`11c512af6bf35ba03541fcc96392bcda579b4e1328a89a4e61b40d423910562c`
- 运行时 fingerprint 中的 `adapter_build_identity`：`HH06_PRECICE_DISPLACEMENT_READ_PATH_AUDIT_ADAPTER_OF10_V1`
- 运行时 fingerprint 中的 `adapter_build_sha256` 与上面一致。
- 该库是从隔离复制的 adapter source 以 OpenFOAM 10 `Allwmake` 构建；生产 adapter、OpenFOAM case、worker、SHM1 均未覆盖。

本次审计 adapter source 的关键 SHA256：

| 文件 | SHA256 |
|---|---|
| `diagnostic_adapter_source/Adapter.C` | `90142EC256174708E2278BB35FAA8E105756FE934B0885DF268ADA2BDB4A1CA5` |
| `diagnostic_adapter_source/Adapter.H` | `73059E038FEC0E3FFAE0B39B8AF1069F5B5AC88EEB014902E7EC85E3DECAB2C2` |
| `diagnostic_adapter_source/Interface.C` | `819E1B8DF9A94B99C70C1290DECCCB9CA9F8F73E82B5D7400C4C5F3D5EBD3662` |
| `diagnostic_adapter_source/FSI/FSI.C` | `4F0C282B1D0ABBACE9612F92D22655213CA143A990FF1F87BE48D883E62E287A` |
| `diagnostic_adapter_source/FSI/Displacement.C` | `201E4443C90D35F2E04C2EE5096AF132CEB8E98C19A967FA4C8A87704A600736` |

## 3. A：数据注册与方向

### OpenFOAM adapter 配置

`case/system/preciceDict`：

- participant：`Fluid_0000`
- mesh：`Fluid-Mesh`
- `readData (Displacement)`
- `writeData (Force)`
- `namePointDisplacement pointDisplacement`
- `nameCellDisplacement cellDisplacement`
- interface locations：`faceCenters`
- coupled patch：`cylinder`

adapter 运行日志确认：

- `Added writer: Force.`
- `Added reader: Displacement.`

### preCICE XML

- `Structure_0000` writes `Displacement` on `Structure-Mesh`。
- `Fluid_0000` reads `Displacement` on `Fluid-Mesh`。
- preCICE 实际输出了 `Mapping "Displacement" for t=0` 和 `t=0.0002`。
- 单窗口内 Structure 发出的 diagnostic-only displacement 为：

  `[1.0452091616563741e-07, 0.00010009588691723237, 0.0004163871573314992] m`

- preCICE displacement convergence norm 分别为 `1.00e-04` 和 `8.00e-05`，说明数据已进入 preCICE 映射/迭代层。

因此，问题不是 XML 中没有声明 `Displacement`，也不是 Structure 没有发送非零值。

## 4. B/C：readData 调用链审计

### 静态调用链

1. `Adapter.C` 配置阶段读取 `preciceDict` 的 `readData`，并通过 `FSI_->addReaders("Displacement", interface)` 注册 `FSI::Displacement` reader。
2. `FSI/FSI.C` 的 `addReaders()` 创建 `new Displacement(mesh_, pointDisplacement, cellDisplacement)`。
3. `Interface.C:577` 的 `Interface::readCouplingData()` 才会调用 `precice_.readData(...)`（preCICE C++ API 返回类型为 `void`），随后调用 `couplingDataReader->read(...)`。
4. `FSI/Displacement.C` 的 `read()` 才会把 buffer 写入 `cellDisplacement` 边界，并通过 `faceToPointInterpolate` 更新 `pointDisplacement` 边界。

### 断点

`Adapter::readCouplingData(double)` 确实存在（`Adapter.C` 约 699 行），并且内部调用 `interfaces_.at(i)->readCouplingData(relativeReadTime)`；但是对整个隔离 adapter source 做 `rg` 审计，没有发现任何生产调用点调用 `Adapter::readCouplingData()`。

实际 `Adapter::execute()` 顺序是：

`writeCouplingData()` → `advance()` → 可选 `readCheckpoint()` → 可选 `writeCheckpoint()` → `adjustSolverTimeStepAndReadData()`。

`adjustSolverTimeStepAndReadData()` 只计算/设置 `deltaT`，没有 `readCouplingData()` 或 `precice_.readData()` 调用。它的名字包含 `ReadData`，但当前实现并不读取 preCICE displacement。

### 运行时证据

隔离 diagnostic adapter 加入了以下 trace：

- `WRITE_DATA_ENTRY/EXIT`
- `READ_DATA_SCHEDULE_ENTRY/EXIT`
- `READ_DATA_ENTRY/EXIT`（只有实际进入 `Adapter::readCouplingData()` 才会出现）
- `Interface::readCouplingData()` 内的 `READ_DATA_CALL_ENTRY`、`READ_DATA_PRECISE_RETURN_VOID`、`READ_DATA_FIELD_USER_APPLIED`

实际 `fluid_rollback_fingerprint.jsonl` 事件顺序为：

`CHECKPOINT_WRITE → WRITE_DATA_ENTRY → WRITE_DATA_EXIT → PRE_ROLLBACK_TRIAL → CHECKPOINT_READ_AFTER_RESTORE → READ_DATA_SCHEDULE_ENTRY → READ_DATA_SCHEDULE_EXIT → AFTER_INPUT_UPDATE → WRITE_DATA_ENTRY → WRITE_DATA_EXIT → READ_DATA_SCHEDULE_ENTRY → READ_DATA_SCHEDULE_EXIT → AFTER_INPUT_UPDATE`

关键结果：

- 没有 `READ_DATA_ENTRY` / `READ_DATA_EXIT`。
- `read_path_trace.jsonl` 不存在，说明隔离的 `Interface::readCouplingData()` 内部 trace 从未执行。
- fluid.stdout 没有 `Reading coupling data...`。

因此可以直接判定：本窗口中 preCICE 收到的 displacement 没有经过 adapter 的 `precice_.readData()` → `CouplingDataUser::read()` 路径。

## 5. D：OpenFOAM field 与动态网格证据

### 关键 fingerprint

| 时点 | pointDisplacement | cellDisplacement | points | oldPoints | meshPhi | max point disp | max cell disp | max mesh velocity | mesh Co |
|---|---|---|---|---|---|---:|---:|---:|---:|
| checkpoint @ 30.0000 | `403a37f08d8872c4` | `054f811aba347c5a` | `84b09858d2e5c718` | `84b09858d2e5c718` | 未注册 | 0 | 0 | 0 | 不可观测 |
| trial @ 30.0002 | `403a37f08d8872c4` | `054f811aba347c5a` | `84b09858d2e5c718` | `84b09858d2e5c718` | `643e6457c48e9183` | 0 | 0 | 0 | 0 |
| restore @ 30.0000 | `403a37f08d8872c4` | `054f811aba347c5a` | `84b09858d2e5c718` | `84b09858d2e5c718` | `643e6457c48e9183` | 0 | 0 | 0 | 0 |
| retry @ 30.0002 | `403a37f08d8872c4` | `054f811aba347c5a` | `84b09858d2e5c718` | `84b09858d2e5c718` | `643e6457c48e9183` | 0 | 0 | 0 | 0 |

OpenFOAM 日志中两次 trial 的 `cellDisplacementx` 和 `cellDisplacementy` 均为：

`Initial residual = 0, Final residual = 0, No Iterations 0`

这与 `cellDisplacement` 没有非零边界输入完全一致。

### motion solver / movePoints

case 的 `dynamicMeshDict` 声明的是：

`motionSolver displacementLaplacian`，`diffusivity quadratic inverseDistance 1(cylinder)`。

但是 motion solver 只有在 `pointDisplacement`/`cellDisplacement` 被更新后才有非零输入。本次运行没有任何正常 displacement-driven `movePoints` 或 `mesh.update` 事件；adapter source 中出现的 `fvMesh::movePoints(meshPoints_)` 仅位于 rollback 的 `reloadMeshPoints()`，用于恢复 checkpoint，不是 displacement read path。fluid.stdout 的 rollback 日志明确记录了这一条恢复调用：`Reading a checkpoint` → `Moving mesh points to their previous locations` → `Moved mesh points to their previous locations`（窗口/迭代由相邻 fingerprint 事件确定为 window 1、iteration 1、30.0002 s rollback）。

`preciceAdapterFunctionObject` 当前只实现 `read/execute/end/write`；其 `updateMesh/movePoints` 回调是注释模板，不是已接入的运行路径。

结论：本窗口中非零 Structure displacement 没有进入 OpenFOAM motion solver；网格未被真正激励。`meshPhi` 的 hash 保持 `643e6457c48e9183`，mesh Courant 为 0。

## 6. 根因分类

`DISPLACEMENT_REGISTERED_BUT_READ_PATH_UNCONNECTED`

更具体地说：

`preCICE mapping/read data layer = PASS`

`OpenFOAM adapter reader registration = PASS`

`Adapter::readCouplingData call path = FAIL`

`FSI::Displacement::read field update = NOT_EXECUTED`

`ALE mesh motion exercise = NOT_EXECUTED`

本审计没有修改 solver 参数、湍流模型、worker、SHM1、preCICE XML 或原始 case；也没有提出或执行修复。

## 7. 证据文件

- 报告：`HH06_PRECICE_DISPLACEMENT_READ_PATH_AUDIT.md`
- 机器结果：`HH06_PRECICE_DISPLACEMENT_READ_PATH_AUDIT_RESULT.json`
- 运行脚本：`run_displacement_read_path_audit.sh`
- fluid stdout：`fluid.stdout`
- participant stdout：`participant.stdout`
- runtime field fingerprints：`fluid_rollback_fingerprint.jsonl`
- readData trace：未生成（因为 `Interface::readCouplingData()` 未被调用）
- adapter source：`diagnostic_adapter_source/`

## 8. 后续边界

本报告只定位了读路径断点。任何修复都应另行授权，且应先在隔离 adapter/case 上做最小 read-path unit/one-window qualification；本轮不修改代码、不进入 50-window 或 production FSI。
