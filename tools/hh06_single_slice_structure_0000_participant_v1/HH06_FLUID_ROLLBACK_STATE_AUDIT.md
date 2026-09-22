# HH06 Fluid Rollback State Audit

审计日期：2026-09-22  
审计对象：`/home/machao/OpenFOAM/coupling/singal_slice/slice0000`  以及其实际加载的 OpenFOAM-preCICE adapter  
执行边界：只读；没有启动 OpenFOAM、preCICE、ANCF，也没有创建或修改新的时间目录。

## 1. 结论摘要

本审计不能把“adapter 源码设计上会保存某字段”误写成“这次失败运行中该字段已经被实际回滚并验证”。结论分为两层：

1. **实际加载的 adapter binary 确实包含 checkpoint/rollback 入口**，并且导出 `readCheckpoint`, `writeCheckpoint`, `readMeshCheckpoint`, `writeMeshCheckpoint`, `setupCheckpointing` 等符号。
2. **现有 release 日志没有在每次 preCICE rollback 回调处输出字段指纹**，而部署 binary 与当前可见源码没有可复现的一一对应证明。因此本次运行中 `U/p/k/omega/nut/phi/points/meshPhi` 的逐字段恢复状态不能被观测性证据直接 PASS。

本次审计状态：

```text
HH06_FLUID_ROLLBACK_STATE_AUDIT = PARTIAL / NOT_EVALUABLE
FLUID_ROLLBACK_COMPLETE = NOT_PROVEN
K_OMEGA_NUT_RUNTIME_RESTORE = UNRESOLVED
PRIMARY_CRASH_CLASS = RAS_TURBULENCE_STATE_BLOWUP_BEFORE_GAMG_FPE
```

这不是“已证明 adapter 只恢复 U/p”的结论。源码层面使用通用 `objectRegistry` 扫描，若 `k/omega/nut` 在 checkpoint 建立时已注册，则它们会进入 `volScalarField` checkpoint；但是当前 binary 的实际字段列表没有运行时回调指纹，故只能标为 **conditional / not observable**。

## 2. 实际运行证据与身份

### 2.1 实际加载库

`controlDict` 使用裸库名 `libpreciceAdapterFunctionObject.so`。本机 OpenFOAM 环境解析到：

```text
/home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libpreciceAdapterFunctionObject.so
SHA256 = 26ad8529822f96ca8ddfb3370f85257b0d19b56958538d6073cf8af897aac572
size   = 1692328 bytes
banner = OpenFOAM-preCICE adapter v1.3.0
BuildID (nm/file audit) = e76f7d6491a2f32cf9d6d5712c79b1ce55cd862b
```

该 ELF binary 导出 checkpoint 相关方法，但没有发现可用于本次运行的字段级 callback trace 接口。

### 2.2 可见源码 provenance

当前可审计源码副本：

```text
D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\openfoam_adapter_v131_rollback_observability_source
git revision = 3d45c38c5091331906bd32517b400d8cb0786bb1
```

该源码显示 v1.3.0 banner，但没有证明它与上面实际加载的 SHA256 binary 是同一构建产物；用当前可见 OpenFOAM10 环境重现构建也因 `faceTriangulation.H` 缺失/不兼容而未形成可比 binary。历史 upstream baseline 记录为 `d53753b1c927b2413b02299c9da15725b3e772f0`，但同样不能替代实际 binary 的精确 source/build provenance。

因此本报告明确区分：

```text
source-level checkpoint design: auditable
deployed-binary callback behavior: symbol-level only
field-by-field runtime identity: not observable
```

## 3. OpenFOAM adapter checkpoint 生命周期

可见 adapter 源码的控制流为：

```text
preCICE initialize()
  -> requiresWritingCheckpoint()
  -> setupCheckpointing()
  -> writeCheckpoint()

每次 execute():
  writeCouplingData()
  advance()
  if requiresReadingCheckpoint(): readCheckpoint()
  if requiresWritingCheckpoint(): writeCheckpoint()
```

对应源码位置：

- `Adapter.C:363-377`：初始化后建立第一次 checkpoint；
- `Adapter.C:413-447`：每个耦合迭代在 `advance()` 后读取或写入 checkpoint；
- `Adapter.C:737-752`：保存/恢复 OpenFOAM `Time` value 和 `timeIndex`；
- `Adapter.C:755-820`：保存/恢复 moving-mesh points，并调用 `mesh_.movePoints()`；
- `Adapter.C:822-841`：专门把 `mesh_.phi()`（meshPhi）加入 mesh checkpoint；
- `Adapter.C:892-926`：按 `mesh_.sortedNames<GeomField>()` 扫描已注册几何场；
- `Adapter.C:1061-1257`：恢复场值及可用的 `oldTime()` 层；
- `Adapter.C:1261-1345`：写入场 checkpoint；
- `Adapter.C:1347-1420`：恢复/写入 mesh checkpoint 场。

该实现是内存副本，不是每次 retry 写入新的 OpenFOAM 时间目录。

## 4. 请求字段审计

| 字段 | OpenFOAM 类型/对象 | 源码设计上是否纳入 | 运行时逐字段身份 | 说明 |
|---|---|---:|---|---|
| `points` | `fvMesh::points()` / `oldPoints()` | YES | NOT_OBSERVABLE | `storeMeshPoints()` 保存；`reloadMeshPoints()` 用 `movePoints()` 恢复。 |
| `meshPhi` | `mesh_.phi()`，`surfaceScalarField` | YES | NOT_OBSERVABLE | `setupMeshCheckpointing()` 显式加入；`readMeshCheckpoint()` 恢复。 |
| `U` | `volVectorField` | YES | NOT_OBSERVABLE | 通用 `volVectorField` 列表复制/恢复，含可用 oldTime。 |
| `p` | `volScalarField` | YES | NOT_OBSERVABLE | 通用 `volScalarField` 列表复制/恢复，含可用 oldTime。 |
| `k` | `volScalarField` | CONDITIONAL YES | NOT_OBSERVABLE | 只要在 `setupCheckpointing()` 执行时已注册到 objectRegistry，就会被通用扫描纳入；本次没有字段列表 callback 证据。 |
| `omega` | `volScalarField` | CONDITIONAL YES | NOT_OBSERVABLE | 与 `k` 相同。 |
| `nut` | `volScalarField` | CONDITIONAL YES | NOT_OBSERVABLE | 与 `k` 相同；没有单独 turbulence 专用分支。 |
| `phi` | `surfaceScalarField` | YES | NOT_OBSERVABLE | 通用 surface-scalar checkpoint；与 `meshPhi` 是不同对象，不能混称。 |
| `Uf` | `surfaceVectorField` | CONDITIONAL YES | NOT_OBSERVABLE | 若对象存在并已注册则纳入；日志曾显示构造 `Uf`，但当前 `30` 目录没有独立 `Uf` 文件。 |
| `pointDisplacement` | `pointVectorField` | YES | NOT_OBSERVABLE | 通用 point-vector checkpoint。 |
| `cellDisplacement` | `volVectorField` | YES | NOT_OBSERVABLE | 通用 volume-vector checkpoint。 |
| `Time/timeIndex` | `Foam::Time` | YES | NOT_OBSERVABLE | 通过 `Time::setTime(value,index)` 恢复。 |
| 拓扑 | polyMesh connectivity | NO dedicated API | NOT_APPLICABLE | 当前 case 拓扑静态；adapter 没有拓扑 checkpoint，需要单独 fingerprint 才能审计。 |

### 4.1 关于 k/omega/nut 的关键限定

源码不是“只保存 U/p”。`setupCheckpointing()` 使用统一宏对注册的 `volScalarField`、`volVectorField`、surface fields、point fields 等进行扫描。若 SST 场在初始化阶段已经注册，`k/omega/nut` 会落入同一类 `volScalarField` 保存/恢复路径。

但这仍然不是本次运行的直接证据，原因是：

1. 实际加载 binary 与可见源码没有精确构建对应证明；
2. release 日志没有打印 checkpoint field names、写入/读取 callback、字段 hash；
3. 当前 `preciceDict` 只声明 coupling data（`Force`/`Displacement`），不声明内部 turbulence checkpoint 清单；字段清单由 adapter 内部 objectRegistry 扫描决定。

因此不能把 `k/omega/nut` 标为 YES/PASS，也不能无证据标为 NO。

## 5. rollback 后是否重新初始化 turbulence？

在可见 adapter 源码中没有搜索到 `turbulence->correct()`、`mesh.update()` 或 `fvModels` rollback/re-initialization 专用调用。恢复动作是：

```text
setTime()
movePoints()
readMeshCheckpoint()
copy checkpointed geometric fields and oldTime levels
```

因此：

- **字段值恢复** 与 **湍流模型重新计算/重初始化** 是两件事；
- adapter 有字段复制路径，但没有显式的 SST `correct()` 回滚后重初始化路径；
- OpenFOAM 后续 solver/PIMPLE 是否在下一轮按正常流程重新计算，不能被称为“rollback 时已重新初始化 turbulence”。

这点与失败信号相关：`k/omega` 在 FPE 之前已经先出现非物理值，说明需要观测 retry 前后 field identity，不能仅看最终 GAMG stack trace。

## 6. 日志中可证明的隐式迭代行为

已有 participant 日志能证明 preCICE 确实进入同一时间窗的多次迭代，例如 RETRY7：

```text
window 3: it 1, it 2, it 3, then time-window completed
...
window 22: it 1, it 2, then Fluid EOF/FPE
```

RETRY11 在 window 18 至少记录了 it 1–it 7，随后用户停止；没有产生新的物理时间目录。

RETRY7 fluid 日志在 `Time = 30.0042 s` 重复出现，且同一物理时刻出现：

```text
Co max = 21.04137642
bounding omega: min -142448.3008, max 120771.218
bounding k: min -9.43608139e-07, max 0.01569340058
```

随后 `Time = 30.0044 s` 出现：

```text
Co max = 14.38620211
bounding omega: min -1.155651408e+09, max 123013.8165
bounding k: min -8.699802771e-07, max 0.01565181103
```

这证明在隐式耦合重试期间存在重复的物理时间/迭代计算和 RAS 场爆炸，但当前日志没有共同的 trial ID 或 adapter callback fingerprint，不能把每一组 `k/omega/Co` 唯一归属到“rollback 前”还是“rollback 后”的某个 iteration。不能据此伪造“第几次 retry 恢复了哪些场”。

## 7. 对用户要求的逐项回答

### A. rollback 时是否恢复字段？

| 字段 | 回答 |
|---|---|
| `points` | 源码设计：YES；本次实际运行：NOT_OBSERVABLE。 |
| `meshPhi` | 源码设计：YES；本次实际运行：NOT_OBSERVABLE。 |
| `U` | 源码设计：YES；本次实际运行：NOT_OBSERVABLE。 |
| `p` | 源码设计：YES；本次实际运行：NOT_OBSERVABLE。 |
| `k` | 条件性纳入通用 `volScalarField`；实际运行：NOT_PROVEN。 |
| `omega` | 条件性纳入通用 `volScalarField`；实际运行：NOT_PROVEN。 |
| `nut` | 条件性纳入通用 `volScalarField`；实际运行：NOT_PROVEN。 |
| `phi` | 源码设计：YES；本次实际运行：NOT_OBSERVABLE。 |

### B. checkpoint 保存在哪里？

adapter 使用内存中的 field copy / mesh copy：

- `Time` 的 value/index：内存变量；
- mesh points/old points：内存 `pointField`；
- `meshPhi`：专用内存 mesh checkpoint；
- 已注册 geometric fields：按类型的内存副本及可用 oldTime；
- 没有证据表明每次 implicit retry 会写出新的 OpenFOAM 时间目录。

### C. rollback 是否恢复 transport/solver 相关状态？

本审计针对 Fluid participant。adapter 明确恢复 OpenFOAM 时间、网格点和 field copies；但没有独立的 preCICE message/transport ID 控制权，也没有显示 solver 内部所有非 field cache 的 checkpoint 清单。`fvMesh` 拓扑不回滚，只能依赖静态拓扑。

### D. rollback 后是否调用 mesh/turbulence 更新？

- `mesh_.movePoints()`：YES，在 moving-mesh rollback 路径中调用；
- `mesh.update()`：源码中未发现 rollback 专用调用；
- `turbulence->correct()`：源码中未发现 rollback 专用调用；
- `fvModels` rollback/update：源码中未发现对应专用调用。

### E. 是否存在“只恢复 U/p、不恢复 k/omega/nut”的证据？

没有足够证据证明这一点。可见源码的通用注册逻辑反而支持 `k/omega/nut` 被纳入；但没有实际 binary/source 对应证明和 runtime field fingerprint，所以正确结论是：**不能声称只恢复 U/p；也不能声称 SST 场已恢复 PASS。状态为 UNRESOLVED。**

## 8. 当前失败的因果定位

已有证据支持以下顺序：

```text
FSI implicit trial/rollback 或运动状态突变
    -> Co 突然升高
    -> k/omega 出现负值/巨大值
    -> GAMG pressure FPE
```

`checkMesh -latestTime` 在最后正常时间 `30` 仍为 Mesh OK，故目前没有证据把首因归为静态网格拓扑损坏。另一方面，由于没有 per-iteration field identity，尚不能在以下两者中做最终二分：

1. rollback 后流体场/网格场没有完整恢复；
2. 圆柱位移/网格速度突变，即使场已恢复，也把 SST 推入失稳。

## 9. 审计状态与后续证据需求

```text
FLUID_ROLLBACK_COMPLETE = NOT_PROVEN
RUNTIME_FIELD_IDENTITY = NOT_OBSERVABLE
NO_CODE_CHANGE = true
NO_CFD_RUN = true
NO_PRECICE_RUN = true
NO_NEW_TIME_DIRECTORY = true
```

若要把这一项从 `NOT_PROVEN` 提升为 `PASS/FAIL`，最小新增证据应是带 callback 级别的 adapter diagnostic build 或等价运行时 tracing：在 `writeCheckpoint()`、`readCheckpoint()` 前后记录同一 trial/window 的 `points, meshPhi, U, p, phi, k, omega, nut, Uf` 指纹，并与 preCICE iteration ID 对齐。本轮没有构建或运行该诊断版本。

