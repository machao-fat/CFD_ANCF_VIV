# INITIAL_PHI_UF_COMPATIBILITY_DIAGNOSTIC_V1

日期：2026-09-09
范围：仅诊断 `PRECURSOR_STATE_V1` 的 `0.100 s` 初始 `phi` 与动态 OF10 `Uf/phi` 重建的相容性；不推进物理时间，不启动 CFD 方程、不重复 Adapter/no-Adapter 单步、不启动非零规定运动或自由 FSI。

## 结论摘要

本轮在真实 zero case 的字段副本上执行了两个无时间推进的诊断：

1. 静止注册状态：读取 `U/p/phi`，按 Foundation OF10 的 `createUfIfPresent.H` 逻辑由 `fvc::interpolate(U)` 构造 `Uf`，计算 `Sf & Uf`。
2. 动态本地状态：在同一副本中只执行 `mesh.update(); mesh.move();`，不执行 `runTime++`、UEqn、pEqn 或写出场，再执行同样的 `CorrectPhi` 局部诊断。

直接测量结果：

- 磁盘 `phi` 的离散散度接近机器精度：`max_abs=2.60146051780873e-10`，`L2=2.89967732047577e-09`。
- 动态路径重建的 `Sf & Uf` 与磁盘 `phi` 在内部面存在明确差异：逐面 `max_abs=5.18088056584295e-03`，`L2=1.66066302671608e-02`；其离散散度为 `max_abs=4.50766807167410`，`L2=11.7289976191596`。
- 实际 patch 差异很小，主要差异在内部面；`outlet` 的 patch 差异仅 `2.38867999990955e-07`，`inlet` 为 `1.09967590589122e-13`，`cylinder/symmetry/empty` 为零。
- 在本地副本上执行 OF10 `correctUphiBCs → CorrectPhi → fvc::makeRelative` 后，`persisted phi` 与校正结果的差异降至 `max_abs=7.15474414826950e-04`、`L2=2.79691027116373e-03`。该诊断没有执行后续 UEqn/pEqn，因此不能把校正后的局部散度当作最终求解连续性误差。
- `-moveMesh` 诊断显示 `mesh_moving=true`、`mesh_changing=true`，并创建了 `meshPhi`；由于输入为零运动，`meshPhi` 全部为零。动态与静止诊断的数值相同，说明差异来自初始 `phi` 与 `Uf`/面通量构造，而不是本地零位移几何变化。

因此，本轮确认了**初始持久 `phi` 与动态 `Sf·Uf` 重建存在内部通量相容性缺口**。这与固定路径和动态路径首步压力/力分支不同的方向一致，但本轮没有推进 CFD，也没有测量力，不能单独证明其解释了全部力差或认定为 OF10 实现缺陷。

当前状态保持：

```text
STRICT_SAME_FVSOLUTION_NO_ADAPTER_PROBE = NOT_EVALUABLE_AS_PURE_SINGLE_FACTOR
ADAPTER_AS_PRIMARY_CAUSE = NOT_SUPPORTED_BY_EXISTING_EVIDENCE
LOCAL_FIXED_ZERO_BRIDGE = FAIL_CLOSED
NEXT_NONZERO_PRESCRIBED_BRIDGE = NOT_AUTHORIZED_PENDING_REVIEW
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

## 1. 输入、源码与 ABI 身份

诊断字段来自：

`runtime/cfd_current_fixed_zero_bridge_v1_run_002/zero_precice_case`

为避免加载 Adapter function-object，建立了隔离副本：

`runtime/cfd_current_fixed_zero_bridge_v1_phi_compatibility_probe_case_v1`

副本只替换 `system/controlDict` 为已有 no-Adapter 控制字典；`0.1` 字段、`constant/polyMesh`、`dynamicMeshDict`、物性和离散字典未改写。该副本没有启动求解器，只供诊断程序读取和在内存中移动网格。

关键输入 SHA256：

| 文件 | SHA256 |
|---|---|
| `0.1/U` | `dd5fd46606bb82a0cfb9a56a282e737f3c9a3cb1c1eebac53b9579da4688b4ac` |
| `0.1/p` | `88ff50b56477b4e38f7921672ab2820137305ca2a40ad754e38817cdc7710a9` |
| `0.1/phi` | `9bfb8d3d1342f8934e4a18dd00d5f4b58ef1d3f4e630c8933b19ffe56a35ff5a` |
| `constant/dynamicMeshDict` | `ba36127272da53fe36ef7ad8eb6d8534a810d13eb95b7d48b8967970aca7333e` |
| `system/fvSchemes` | `8dde725a7774d93a6ad1203b88f8fcc8eed5c87d1f155cad91716c079c9c4f26` |
| `system/fvSolution` | `981465e887c0ae1c6e5d6a7cd6277c08ecfc01fee188c7387b81f74ceb3ab7ef` |

实际使用的 Foundation OF10 构建为 `10-c4cf895ad8fa`，前缀为：

`/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10`

诊断程序：

`tools/cfd_current_fixed_zero_bridge_v1/phi_compatibility_probe/phiCompatibilityProbe.C`

构建产物 realpath：

`/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/phi_compatibility_probe_build_001/bin/phiCompatibilityProbe`

SHA256：`ef49e4d35d74c0ee94df1ea169f1ac515cb682dfcff2f3ceac31d8b375cb8172`

关键库 SHA256：

| 库 | SHA256 |
|---|---|
| `libOpenFOAM.so` | `a34df8ad17f8250071c697d150e593563f2152c194b87fdb906b7a6493f37cde` |
| `libfiniteVolume.so` | `5a820734c0a61a8bd6cdb730d95a651e002848d9d9d4d8a4897ea42608a2e48e` |
| `libfvMeshMovers.so` | `da199da31b42a7b5e07248864cb91c6556dba0afa4db74507879f4124d307e78` |
| `libfvMotionSolvers.so` | `debc2c86635805c616874612c9c361477424ec58cba77ccc46853b786750eb30` |

在运行时 `ldd -r` 中，OpenFOAM 库均解析到上述 owner-diagnostic 前缀；MPI、libstdc++、libm、libc 来自系统目录；没有 `not found` 或未解析符号。原始 `/opt/openfoam10`、build005/006/007、生产 Adapter 和历史 runtime 未改动。

可复现构建命令（WSL，未改动 OF10 源码）：

```bash
source tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh \
  /home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001
export FOAM_USER_APPBIN=/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/phi_compatibility_probe_build_001/bin
cd tools/cfd_current_fixed_zero_bridge_v1/phi_compatibility_probe
wmake
```

诊断只读取隔离副本；`-moveMesh` 仅在进程内执行一次本地 `mesh.update()/mesh.move()`，没有 `runTime++`、求解器推进或 case 字段写出。

## 2. OF10 实际调用语义

实际 Foundation OF10 源码中的相关语义为：

- `createPhi.H` 构造 `surfaceScalarField phi`，使用 `IOobject::READ_IF_PRESENT` 和 `fvc::flux(U)` 作为缺失时的构造值。本 case 的 `0.1/phi` 存在，因此诊断读取持久场。
- `createUfIfPresent.H` 在动态网格上构造注册的 `Uf`，使用 `IOobject::READ_IF_PRESENT` 和 `fvc::interpolate(U)` 作为缺失时的构造值。本 case 没有 `0.1/Uf`，因此走 `fvc::interpolate(U)`。
- 动态路径先调用 `mesh.update()`，再由 motion solver 执行 `mesh.move()`；本地 `-moveMesh` 诊断只在内存副本中执行这两步，不推进 `Time`。
- `correctPhi.H` 的顺序为 `phi = mesh.Sf() & Uf()`、`correctUphiBCs(U, phi, true)`、`CorrectPhi(...)`、`fvc::makeRelative(phi, U)`。本诊断对本地字段副本调用同一组 OF10 操作。
- `fvSolution` 保持 `correctPhi yes`、`correctMeshPhi yes`、Euler、`nOuterCorrectors=1`、`nCorrectors=2` 及原有 pcorr/PIMPLE 容差；没有为诊断关闭或放宽校正。

诊断没有调用 `oldTime()`、`Uf()`、`meshPhi()` 等可能 demand-create 历史的 getter；`meshPhi` 仅用 `foundObject<surfaceScalarField>("meshPhi")` 检查，存在时才读取已在 registry 中的对象。

## 3. 逐面数值结果

### 3.1 静止与本地动态注册状态

两次诊断均读取 `16244` 个内部单元和 `24506` 个内部+边界面值。`Uf` 的面矢量幅值统计为 `count=24506`、`min=0`、`max=1.70822789379849`、`L2=157.477086007596`。

| 量 | persisted `phi` | reconstructed `Sf·Uf` |
|---|---:|---:|
| count | 24506 | 24506 |
| min | -0.608555923181000 | -0.608669847895557 |
| max | 0.638427885965000 | 0.638526050831444 |
| L2 | 39.9696576038148 | 39.9697927834794 |
| sum | 185.457711562349 | 185.449100000452 |
| boundary sum | `2.53006504635778e-10` | `-4.45748497668319e-07` |
| `max_abs(div)` | `2.60146051780873e-10` | `4.50766807167410` |
| `L2(div)` | `2.89967732047577e-09` | `11.7289976191596` |

`persisted - reconstructed` 的全场差异为 `max_abs=5.18088056584295e-03`、`L2=1.66066302671608e-02`。逐 patch 最大差异为：

| patch | max abs |
|---|---:|
| `outlet` | `2.38867999990955e-07` |
| `inlet` | `1.09967590589122e-13` |
| `cylinder` | `0` |
| `symmetry/empty` | `0` |

因此差异主要位于内部面，而不是 cylinder fixed-value 边界值或 patch 类型。

### 3.2 局部 CorrectPhi 结果

在同一内存副本上执行 `correctUphiBCs → CorrectPhi → makeRelative` 后：

- pcorr 日志：初始残差 `1`，最终残差 `0.00469713118572`，`3` 次迭代；这是中间通量投影，不是完整 p 方程终端残差。
- `persisted - corrected`：`max_abs=7.15474414826950e-04`、`L2=2.79691027116373e-03`。
- 校正结果内部离散散度：`max_abs=0.0132088960193799`、`L2=0.0459552911769231`。
- 校正后边界 patch 差异仍很小，outlet 最大 `6.13259987142234e-06`，inlet 约 `1.1e-13`，cylinder 为零。

本诊断没有执行 UEqn、pEqn 和完整时间步，所以校正后内部散度不能替代运行时最终 continuity 记录。它只证明 CorrectPhi 会显著改变由 `Sf·Uf` 得到的初始通量，并使其靠近持久 `phi`，但不把两者变成逐面相同。

### 3.3 mesh.move 只读检查

静止模式报告 `mesh_moving=false`、`mesh_changing=false`、`meshPhi_present=false`。`-moveMesh` 模式报告 `mesh_moving=true`、`mesh_changing=true`、`meshPhi_present=true`；`meshPhi` 的 `24506` 个值全部为零。两种模式的 `phi/Uf` 数值相同，这是零位移输入下的预期几何结果，同时证明动态分支已被实际调用。

## 4. 因果解释边界

### 已证明

1. 持久 `phi` 本身是近似散度一致的；动态缺失 `Uf` 由 `fvc::interpolate(U)` 合法重建，但 `Sf·Uf` 并不等于该持久 `phi`。
2. 差异主要在内部面，边界 patch 并未被非零运动或错误 fixedValue 覆盖。
3. 动态零运动路径仍会创建 `meshPhi`、执行 `mesh.move` 语义和 CorrectPhi；“零运动”不等于固定路径跳过动态通量分支。
4. CorrectPhi 对该不相容有明显投影作用；其 pcorr 中间残差不应被直接解读为最终压力方程失败。

### 尚未证明

1. 本轮没有推进真实 CFD 时间步，不能由该 probe 单独给出压力力差的定量因果闭合。
2. 不能仅凭差异判断持久 `phi` 的来源错误、OF10 实现错误或某个特定离散格式错误；需要追溯生成 `0.1/phi` 的前置场导出路径及其 face-interpolation 语义。
3. CorrectPhi 后仍有非零局部散度是因为没有继续执行真实 UEqn/pEqn；它不是新的生产求解失败证据。

### 已排除或不支持

- 本轮未发现几何运动导致的差异：`meshPhi` 为零，点位移为零。
- 不能把该现象归因于 Adapter；本轮没有重复 Adapter/no-Adapter CFD，且既有运行已显示两条动态路径输出一致。
- 不能通过关闭 CorrectPhi、强制初始化历史、修改 PIMPLE 或放宽容差消除该差异；这些都不在本轮授权范围内。

## 5. 决策

初始通量相容性已经从“不可观测”推进为“存在内部面不相容、机制方向明确但力学量级尚未闭合”。因此本轮不授权进入非零规定运动桥接。下一步只能在人工批准后选择一个最小、可比较的来源追踪实验，例如在同一 OF10 生产前置场副本中追溯 `0.1/phi` 的生成算子并与 `fvc::flux(U)` 逐面比较；不得通过关闭 CorrectPhi 或重跑完整 CFD 来制造一致性。

`Persistent U/Uf oldTime` 指纹缺口仍是独立资格项，本报告不把它认定为当前零运动首步力差的根因。

## 6. 证据索引

- 静止诊断 JSON：`results/cfd_current_fixed_zero_bridge_v1_phi_compatibility_probe_v1/phi_compatibility_isolated_static.json`
- 动态本地诊断 JSON：`results/cfd_current_fixed_zero_bridge_v1_phi_compatibility_probe_v1/phi_compatibility_isolated_moved.json`
- 原始 zero case：`runtime/cfd_current_fixed_zero_bridge_v1_run_002/zero_precice_case`
- 诊断隔离副本：`runtime/cfd_current_fixed_zero_bridge_v1_phi_compatibility_probe_case_v1`
- 诊断源码：`tools/cfd_current_fixed_zero_bridge_v1/phi_compatibility_probe/phiCompatibilityProbe.C`
- 构建脚本：`tools/cfd_current_fixed_zero_bridge_v1/phi_compatibility_probe/Make/files`、`Make/options`
- 既有严格零运动审计：`docs/cfd_current_fixed_zero_bridge_v1/STRICT_SAME_FVSOLUTION_NO_ADAPTER_PROBE_V1_REPORT.md`
- 既有固定—动态因果审计：`docs/cfd_current_fixed_zero_bridge_v1/CFD_CURRENT_FIXED_ZERO_CORRECTION_CAUSAL_REVIEW_V1.md`
