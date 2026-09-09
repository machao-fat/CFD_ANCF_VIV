# 固定网格—动态零运动首步差异因果审议

**任务**：`CFD_ANCF_VIV` 当前生产 CFD 验证桥接

**日期**：2026-09-09

**对象**：`cfd_current_fixed_zero_bridge_v1_run_002`、历史 `fixed_restart`/`zero_motion_dynamic_restart`，以及实际隔离 Foundation OF10 源码。

## 1. 结论摘要

本轮没有修改 `correctPhi`、PIMPLE、物性、网格或生产源码，也没有启动非零运动或自由 FSI。

已证明：

1. 固定组、真实 preCICE 零运动组和 `PRECURSOR_STATE_V1` 在 `0.100 s` 的 `U/p/phi` 是逐字节相同的；结构化字段解析也确认 internalField 和所有 value-backed boundary patch 一致。
2. 历史无 Adapter 的 `zero_motion_dynamic_restart` 与本次真实 Adapter 零运动组在 `0.105–0.120 s` 写出的 `U/p/phi/pointDisplacement/cellDisplacement/meshPhi` 逐字节相同；两次使用同一 Foundation OF10 `pimpleFoam` build 字符串 `10-c4cf895ad8fa`。这把 Adapter/preCICE 非零输入排除为首要原因。
3. 动态路径即使输入位移为零，也会执行 `motionSolver::update() → fvMesh::movePoints()`，构造 `Uf`、`meshPhi` 并进入 `correctPhi`；固定路径没有这些分支。
4. 首个差异确实发生在 `0.105 s` 动态网格校正分支：零运动日志先出现零迭代 `cellDisplacementx/y` 和 `pcorr`，再进入 U/p 求解。该 `pcorr` 是中间通量校正残差，不等同于最终 PIMPLE 压力残差或 solver hard failure。

因此当前最准确的分类是：

```text
CAUSE_CLASS = DYNAMIC_ALE_FLUX_CORRECTION_WITH_UNRESOLVED_INITIAL_FLUX_COMPATIBILITY
ADAPTER_AS_PRIMARY_CAUSE = NOT_SUPPORTED_BY_EXISTING_EVIDENCE
LOCAL_FIXED_ZERO_BRIDGE = FAIL_CLOSED
STRICT_SAME_FVSOLUTION_NO_ADAPTER_PROBE = NOT_EVALUABLE (setup failure; solver not started)
```

它可以是合法的 OF10 动态通量校正造成的分支差异，但尚不能称为“已达到目标数值精度”；首步总力差为 `72.274 N`，远大于原先预声明的 `1e-6 N / 1e-8` 力一致性判据。也没有证据证明某个 OF10 函数实现错误。非零规定运动桥接暂不授权。

## 2. 可靠字段复核

### 2.1 旧解析器的问题

原 `field_comparison.json` 的解析器从 `dimensions` 后搜索全部数字，因而把 nonuniform list count、boundary 元数据和字典数字混入 field 数据。例如：

| 字段 | 正确 internalField | 旧 numeric_count | 旧 max_abs 中混入的值 |
|---|---:|---:|---:|
| `U` | `16244×3 = 48732` | `48920` | `16244`（list count） |
| `p` | `16244` | `16246` | `16244`（list count） |
| `pointDisplacement` | uniform 内部值 3，另有 3 个 fixedValue patch | `12` | 不能区分 internal/boundary |
| `cellDisplacement` | uniform 内部值 3，另有 cylinder patch 3 | `6` | 不能区分字段区域 |
| `meshPhi` | uniform 内部值 1，patch value 按 patch 解析 | `8` | 混入两个 empty patch 的 `0()` count |
| `Uf` | `24226×3 = 72678` | `73230` | 混入 list count/边界信息 |

本轮新增的结构化只读解析器 [`inspect_openfoam_fields.py`](../../tools/cfd_current_fixed_zero_bridge_v1/inspect_openfoam_fields.py) 分开读取：`class/object/dimensions`、`internalField` 的 kind/count/arity/value hash、每个 boundary patch 的 type 和 value-backed entries。它不构造 OpenFOAM 对象，不调用 `oldTime()`、`Uf()`、`meshPhi()` 或任何 demand-driven getter。

### 2.2 初始字段

`0.100 s` 的 `U/p/phi`：

| 比较 | byte SHA 是否相同 | 结构化 internal/boundary 是否相同 |
|---|---|---|
| fixed vs real preCICE zero | 是 | 是 |
| fixed vs PRECURSOR_STATE_V1 | 是 | 是 |
| zero vs PRECURSOR_STATE_V1 | 是 | 是 |

代表性完整解析数量如下：

- `U`：16244 个内部 vector（48732 个分量）；outlet 60 个 vector，inlet/cylinder 为 uniform vector；
- `p`：16244 个内部 scalar；outlet 为 uniform fixedValue，其余 patch 类型按实际字典读取；
- `phi`：24226 个内部 scalar；inlet/outlet 的 nonuniform patch value 逐项解析；
- 初始点位移和单元位移文件也逐字节相同。

所以当前首步差异不是磁盘中 `U/p/phi` 起点不一致。两组 `0.100` 目录都没有 `Uf`、`meshPhi` 或 `uniform/time` 文件；这表示这些量在动态运行中按 OF10 生命周期创建，不能从磁盘缺失直接判定为错误。输出目录中也没有名为 `oldTime` 的持久文件；内存 oldTime 层仍须按运行时合同单独处理，不能由目录扫描冒充可观测。

## 3. Foundation OF10 实际调用链

源码来自独立 OF10 树：

`/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10`

关键文件和语义：

1. `applications/solvers/incompressible/pimpleFoam/createFields.H` 读取 `p`、`U`，随后 include `src/finiteVolume/cfdTools/incompressible/createPhi.H`。
2. `createPhi.H` 用 `IOobject::READ_IF_PRESENT` 读取已有 `phi`，缺失时才用 `fvc::flux(U)` 构造。因此本 case 的 persisted `phi` 起点被保留。
3. `createUfIfPresent.H` 仅在 `mesh.dynamic()` 时构造 `Uf`，使用 `READ_IF_PRESENT`，缺失时以 `fvc::interpolate(U)` 初始化。本 case 的 `0.1/Uf` 不存在，所以动态组确实走该初始化分支；固定组不创建 `Uf`。
4. `pimpleFoam.C` 每步先 `mesh.update()`，再 `runTime++`，然后在 PIMPLE 首次迭代执行 `mesh.move()`。当前 `dynamicMeshDict` 选择 `motionSolver/displacementLaplacian`。
5. `fvMesh::move()` 调用 `mover_->update()`。`fvMeshMovers::motionSolver::update()` 无条件调用 `mesh().movePoints(motionPtr_->newPoints())`；即使新点与旧点数值相同，也走动态 `movePoints` 生命周期。
6. `fvMesh::movePoints()` 在时间索引前进时保存体积历史；若不存在则创建 `meshPhi`，以 swept volume/`deltaT` 填充 mesh flux，并更新几何、边界和插值对象。
7. `pimpleFoam.C` 在 `mesh.changing()` 且 `correctPhi` 为真时 include `correctPhi.H`。当前 `fvSolution` 明确设置 `correctPhi yes; correctMeshPhi yes;`，而 `createDyMControls.H` 的默认规则也是动态网格默认开启 `correctPhi`。
8. `correctPhi.H` 先执行 `phi = mesh.Sf() & Uf()`，再 `correctUphiBCs(U, phi, true)`，调用 `CorrectPhi(...)` 解 `pcorr` 使通量连续，最后 `fvc::makeRelative(phi, U)`。
9. 后续 `pEqn.H` 完成压力方程后调用 `fvc::correctUf(Uf, U, phi, MRF)`，再执行 `fvc::makeRelative(phi, U)`。因此 `pcorr` 中间残差与最终 p 方程残差属于不同阶段。

该调用链说明：动态零运动并不等同于固定路径的“跳过所有 mesh/ALE 操作”。即使 `pointDisplacement` 和 swept `meshPhi` 为零，也会因动态字段生命周期和 `phi/Uf` 相容性校正而产生不同离散路径。

## 4. 旧无 Adapter 证据与当前真实 Adapter 证据

### 4.1 输出逐字节复现

历史目录：

`runtime/fixed_cylinder_precursor_initialization_v1_run_002/zero_motion_dynamic_restart`

当前目录：

`runtime/cfd_current_fixed_zero_bridge_v1_run_002/zero_precice_case`

在 `0.105/0.110/0.115/0.120 s`，以下文件逐字节相同：

`U`, `p`, `phi`, `pointDisplacement`, `cellDisplacement`, `meshPhi`。

两次 stdout 都记录 `Build : 10-c4cf895ad8fa`、`Exec : pimpleFoam`，当前组另外加载了真实 Adapter 和 preCICE。该结果支持：零参与者输入、Force 传输或 Adapter function-object 不是产生首步差异的主要因素。

### 4.2 数值字典差异限制

两组并非文件级完全同构：历史旧组 `fvSolution` 少一个当前组的 `cellDisplacement` solver 条目；`fvSchemes`、`dynamicMeshDict`、物性和主要运动配置相同。旧组输出仍逐字节复现当前 Adapter 组，说明该额外条目在零运动轨迹上没有表现为输出差异，但严格“只去掉 Adapter、其余完全相同”的隔离证据尚未取得。

本轮按授权尝试建立该严格单步 probe，目录为：

`runtime/cfd_current_fixed_zero_bridge_v1_run_003_no_adapter_dynamic_one_step`

脚本在写入 test-only `controlDict` 时因 Python `Path.write_text(..., newline=...)` 参数错误退出，`solver_started=false`，没有 OpenFOAM/preCICE 进程、没有 CFD 输出。原始 setup blocker 保留在 `setup_failure.txt`；脚本已修正，但按“不自动重跑”边界没有再次启动。

## 5. 首步差异和收敛含义

有效 `_run_002` 在 `0.105 s`：

| 量 | fixed | real preCICE zero |
|---|---:|---:|
| `pcorr` 首次日志 | 不出现 | initial `1` → final `4.697131e-3`，3 iter |
| `U` 终端最大 residual | `8.511433e-5`（p 首次） | `3.884410e-3`（p 首次） |
| 第二次 p 终 residual | `6.520928e-9` | `5.634965e-9` |
| 全局 continuity（首轮） | `2.596100e-12` | `1.987637e-11` |
| total Fx | `1320.477922 N` | `1248.203924 N` |
| total Fy | `-8.157111 N` | `-45.965786 N` |

`pcorr` 首轮残差低于当前 `pcorrFinal` 的 `1e-2` 数值容差，且最终 p 方程残差和连续性均继续下降；所以不能把 `pcorr` 的中间值直接称为最终求解失败。另一方面，动态组的压力/力差并非仅由日志残差标签决定，且后续总力差仍为数 N 量级，故不能把固定—动态差异宣布为已达到固定的严格力一致性精度。

## 6. 因果判定

### 已证明

- 初始 `U/p/phi` 和所有已写出的 value-backed 边界值一致；旧解析器的数字污染已纠正。
- 动态组缺失 `Uf/meshPhi` 初始文件是合法的生命周期形态：OF10 明确 demand-constructs `Uf`，`fvMesh::movePoints` 明确创建 `meshPhi`。
- 动态 zero 与真实 Adapter zero 的输出在可比时间层逐字节一致；Adapter/preCICE 不是当前首要差异源。
- 差异的第一操作级位置是 `mesh.move → CorrectPhi/pcorr → UEqn/pEqn` 分支，而不是非零位移或网格点改变。

### 最可能机制（尚未证明为唯一根因）

当前 `phi` 是 precursor 持久场，`Uf` 在动态组由 `fvc::interpolate(U)` 新建；`correctPhi` 随后把 `phi` 重置为 `mesh.Sf & Uf` 并做连续性校正。即使几何 swept volume 为零，这个“persisted phi + lazily reconstructed Uf + CorrectPhi”组合也可能改变首步压力初值和压力力。它符合 OF10 设计的 restart/mesh-change flux correction 语义，但本轮尚未证明其与当前 precursor 的数值相容性达到目标精度。

### 已排除或不支持

- 真实 preCICE 参与者发出非零运动：不支持，10 步全零输入且 point/cell displacement 为零。
- Adapter 写入错误 Force：不支持，参与者收到的 Force 与零组 OpenFOAM total force 逐步一致。
- 首步差异来自固定/动态初始 `U/p/phi` 文件内容不一致：不支持，逐字节和结构化比较均一致。
- `pcorr` 中间 residual 本身等同于最终 PIMPLE 失败：不成立，后续压力 residual 达到 `~5.6e-9`，连续性继续收敛。

### 尚未闭合

- 尚未取得“当前完整 `fvSolution` + dynamicMeshDict、仅去掉 Adapter”的有效单步无 Adapter 输出；本轮 probe 被 test harness setup blocker 阻止，不能用失败脚本冒充该证据。
- 尚未从运行时无副作用地直接记录 `correctPhi` 前后的 `phi/Uf` 内存值；磁盘输出只能证明后处理结果，不能伪造 before/after。
- 当前 fixed/dynamic 力差是否在论文所需物理精度内可接受，尚未定义独立的动态基线容差；现有严格 `1e-6 N/1e-8` gate 仍 FAIL_CLOSED。

## 7. 决策与下一步

本轮不建议直接进入非零规定运动桥接。最小下一步仍是一次严格单因素 probe：复用同一 `PRECURSOR_STATE_V1`、当前 `fvSolution`、`fvSchemes`、`dynamicMeshDict` 和 `dt`，只去掉 Adapter/preCICE，单步 `0.100→0.105 s`，比较 `pcorr` 前后可观测输出、`phi/Uf`、最终 `p/U/force`。该实验只用于区分：

- A：差异由 OF10 动态/ALE/`CorrectPhi` 路径本身产生；
- B：差异由 Adapter function-object 的初始化或执行时序产生。

本轮不自动修正 setup blocker、不自动重跑该 probe、不关闭 `correctPhi`、不放宽容差，也不启动非零运动。

状态保持：

```text
NEXT_NONZERO_PRESCRIBED_BRIDGE = NOT_AUTHORIZED_PENDING_REVIEW
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

相关离线证据：

- [`field_parser_audit.json`](../../results/cfd_current_fixed_zero_bridge_v1_run_002/field_parser_audit.json)
- [`bridge_result.json`](../../results/cfd_current_fixed_zero_bridge_v1_run_002/bridge_result.json)
- [`field_comparison.json`](../../results/cfd_current_fixed_zero_bridge_v1_run_002/field_comparison.json)
- [`inspect_openfoam_fields.py`](../../tools/cfd_current_fixed_zero_bridge_v1/inspect_openfoam_fields.py)
- [`run_no_adapter_dynamic_probe.py`](../../tools/cfd_current_fixed_zero_bridge_v1/run_no_adapter_dynamic_probe.py)
