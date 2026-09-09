# 当前生产 CFD 固定圆柱—真实 preCICE 零运动桥接报告

**任务**：`CFD_ANCF_VIV` 最小 CFD 验证桥接

**日期**：2026-09-09

**范围**：当前生产 expanded-medium 圆柱、`PRECURSOR_STATE_V1` 起点、固定圆柱参考路径与真实 preCICE–adapter 全零位移路径的一次短时对照。

**边界**：本轮没有修改生产源码、OF10-owned restore、adapter、网格、物理参数、`dt`、PIMPLE 或历史 runtime；没有启动非零规定运动、自由 FSI、三切片 0.05 s 重跑或长时间算例。旧的 0.05 s `FAIL_CLOSED`、W10 证据和所有历史 FAIL 保持不变。

## 1. 结论

本次有效对照 `_run_002` 的两个 OpenFOAM 进程都完成了 10 个时间步并返回 0，真实 preCICE 零位移参与者也完成 10 次 `advance`，但固定圆柱与真实零运动路径的力未达到预先冻结的逐步容差。因此本地桥接结论为：

```text
LOCAL_FIXED_ZERO_BRIDGE = FAIL_CLOSED
NEXT_NONZERO_PRESCRIBED_BRIDGE = NOT_AUTHORIZED_PENDING_REVIEW
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

首个数值差异发生在第一个推进步 `0.100 -> 0.105 s`：零运动动态网格路径先执行 `cellDisplacement`/`pcorr` 分支，随后压力场和圆柱压力力与固定路径分离。此时点位移、单元位移和 `meshPhi` 的数值仍为零、网格点身份不变；所以当前证据支持“真实动态/ALE 求解分支与固定网格分支不局部一致”，但尚不足以把根因归结为某一个生产源码函数。

这不是物理 VIV 结论，也不是对当前耦合力放大的最终根因判定。

## 2. 证据与运行身份

### 2.1 为什么需要新对照

已有 `fixed_restart`/`zero_motion_dynamic_restart` 只覆盖到 `0.120 s`，且零运动分支没有真实 preCICE Adapter；已有真实 Adapter 零运动 probe 只推进一个时间步。因此不能直接证明当前生产 `pimpleFoam + displacementLaplacian + preCICE` 路径与固定圆柱路径在同一起点逐步一致。本轮建立了独立、不可覆盖的短时 runtime；没有改写历史结果。

### 2.2 输入身份

| 项目 | 采用值 |
|---|---|
| 起点/终点 | OF `0.100 -> 0.150 s` |
| 时间步/步数 | `dt=0.005 s`，10 步 |
| 起始场 | `PRECURSOR_STATE_V1` 的 `U/p/phi`，源时间 `0.100 s` |
| 网格 | 当前正式三切片 slice 0 的 expanded-medium 网格，16244 cells |
| 网格文件 | points `fbdbb5f4...9012f`；faces `68c0fb45...2693c`；owner `1cf77560...0aed`；neighbour `d331ed5d...45cf`；boundary `5d13f8b4...3ceb4f` |
| 固定组 | 删除 `dynamicMeshDict`，直接运行同一 `pimpleFoam` 数值字典和 `cylinderForces` |
| 零运动组 | 保留 `displacementLaplacian`、`pointDisplacement/cellDisplacement`，加载真实 `libpreciceAdapterFunctionObject.so`；Structure participant 每步写入完整零位移 |
| 力判据 | 每个 pressure/viscous/total 分量 `abs <= 1e-6 N` 且 `rel <= 1e-8` |
| 几何判据 | 对可比较的点位置 `max_abs <= 1e-12 m` |
| Adapter | `c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17` |
| OF10 ABI | 独立 `owner_diagnostic_abi_build_001`；运行时未使用 `/opt/openfoam10`。核心库与完整 `ldd -r` 闭包沿用正式候选 manifest |

结果索引：

- 有效结果：[`bridge_result.json`](../../results/cfd_current_fixed_zero_bridge_v1_run_002/bridge_result.json)
- 字段/网格离线比较：[`field_comparison.json`](../../results/cfd_current_fixed_zero_bridge_v1_run_002/field_comparison.json)
- 运行脚本：[`run_fixed_zero_bridge.py`](../../tools/cfd_current_fixed_zero_bridge_v1/run_fixed_zero_bridge.py)、[`analyze_bridge.py`](../../tools/cfd_current_fixed_zero_bridge_v1/analyze_bridge.py)
- 有效 runtime：[`cfd_current_fixed_zero_bridge_v1_run_002`](../../runtime/cfd_current_fixed_zero_bridge_v1_run_002)

本轮提交的可复现小文件 SHA256：

```text
run_fixed_zero_bridge.py  E0E65B929B3A28C3AE6DC943F74325D7EC32F0973529D4309D84EA0934131559
analyze_bridge.py         5767BE0320E7BFCA25D85DB4D9A6FBEBBEF5A1B1C90D4F5D4B3EA173EB5F2CE0
bridge_result.json        4F1020F6F5C36D8023E521C3ADBA7995AF667EB92F48854B85909462181851AA
field_comparison.json     AE7F0845FF103741918ABF96BA6BA5FBD6AF596B7C5BFE4F42DAF92C82E9E5BE
```

复现命令（只对已有 runtime 做准备/运行或离线解析；本报告形成后没有再次启动 CFD）：

```text
python tools/cfd_current_fixed_zero_bridge_v1/run_fixed_zero_bridge.py
python tools/cfd_current_fixed_zero_bridge_v1/analyze_bridge.py
```

### 2.3 首次测试配置失败（保留，不计入数值结果）

`_run_001` 在 OpenFOAM 推进前因测试专用 preCICE XML 的 mesh 声明错误退出：`Structure_0000` 的数据使用了错误的 `Fluid-Mesh`。该错误只属于本次测试配置，未改动生产 XML 或生产语义。修正为 Structure 使用 `Structure-Mesh`、Fluid 通过 mapping 接收/提供 `Fluid-Mesh` 后才执行 `_run_002`；`_run_001` runtime 保留为原始证据。

## 3. 运行结果

两组在 `t=0.100 s` 的初始 force 行逐分量完全相同。零参与者证据记录 `initial_data_requested=true`、10 步、所有位移输入为零；每一步收到的 Force 求和与零运动 OpenFOAM `cylinderForces` 总力相差约 `1e-12 N`，说明本次 preCICE 传输和零输入参与者内部映射一致。

下表只列 10 个推进时间层。`ΔF = F_zero - F_fixed`；`Δphi/p/U` 是零运动字段相对固定组的逐分量最大绝对差。Co 是各组该时间层日志中的最大值。

| t (s) | ΔFx (N) | ΔFy (N) | Δphi | Δp | ΔU | Co fixed / zero |
|---:|---:|---:|---:|---:|---:|---:|
| 0.105 | -72.2740 | -37.8087 | 5.318e-4 | 2.878e-1 | 2.250e-2 | 0.35030 / 0.35030 |
| 0.110 | +21.4168 | +7.9216 | 2.937e-4 | 2.822e-2 | 1.777e-2 | 0.35003 / 0.35010 |
| 0.115 | +7.2893 | +4.2806 | 2.770e-4 | 1.362e-2 | 1.394e-2 | 0.34971 / 0.34976 |
| 0.120 | +5.8804 | +3.8343 | 2.722e-4 | 1.094e-2 | 1.075e-2 | 0.34933 / 0.34937 |
| 0.125 | +5.3646 | +3.6515 | 2.673e-4 | 9.510e-3 | 8.172e-3 | 0.34891 / 0.34893 |
| 0.130 | +4.6535 | +3.1600 | 2.557e-4 | 8.297e-3 | 6.377e-3 | 0.34845 / 0.34845 |
| 0.135 | +4.1659 | +2.6770 | 2.345e-4 | 7.495e-3 | 5.151e-3 | 0.34794 / 0.34794 |
| 0.140 | +3.5669 | +2.3222 | 2.105e-4 | 6.608e-3 | 4.167e-3 | 0.34741 / 0.34739 |
| 0.145 | +2.9861 | +1.9909 | 1.903e-4 | 5.834e-3 | 3.377e-3 | 0.34685 / 0.34682 |
| 0.150 | +2.4533 | +1.5811 | 1.705e-4 | 5.155e-3 | 2.977e-3 | 0.34626 / 0.34623 |

全部 10 个推进时间层的 force 判据均失败；`.105 s` 是首次偏离。固定组与零运动组均无进程级 FPE，日志均正常到 `End`。本对照没有单独运行 `checkMesh`，所以不把它写成新的 mesh-quality PASS；几何点 identity 与零位移数值见下一节。

## 4. 状态和几何证据

- 零运动组每个输出时间层 `pointDisplacement` 的数值最大绝对值为 `0`，`cellDisplacement` 为 `0`，`meshPhi` 为 `0`。
- fixed 与 zero 的 `constant/polyMesh/points` SHA 在所有时间层相同；没有观察到圆柱点或网格点运动。
- fixed 组没有 `pointDisplacement`、`cellDisplacement`、`meshPhi`、`Uf` 输出，这是固定网格路径的预期 inventory 差异，不能把“文件不存在”当成动态组状态丢失。
- zero 组有 `Uf` 和 `meshPhi`，它们属于动态路径的派生输出；本轮只验证其数值为零/存在，不宣称已经闭合完整 oldTime inventory。
- `phi`、`p`、`U` 在第一推进步即出现非零差异并随后衰减，故“零位移意味着两条离散路径必然逐步 bitwise 相同”不成立。

## 5. 首个分支差异和因果边界

在 `t=0.105 s` 日志中，固定组直接进入 `U/p` 求解；零运动动态组先出现：

```text
DICPCG cellDisplacementx initial=0 final=0 iterations=0
DICPCG cellDisplacementy initial=0 final=0 iterations=0
GAMG pcorr initial=1 final=0.00469713118572 iterations=3
```

随后零运动组的压力求解最大终残差为 `4.697e-3`，固定组对应最大终残差为 `8.511e-5`；两者连续性全局误差仍分别约 `2.0e-11` 和 `2.6e-12`。这给出了“首次操作级差异在动态网格的 displacement/`pcorr` 校正分支”的直接日志证据。它没有证明 `correctPhi`、`pcorr` 或某个具体库函数就是唯一根因，后续若继续只能做一个单因素、同起点的动态分支隔离实验。

同一差异曾在既有无 Adapter 的 `zero_motion_dynamic_restart` 证据中出现；本次真实 Adapter 零运动对照再次复现，因而不能把它归因于本次 Structure participant 写入了非零位移或 Force 传输错误。与此同时，这个结果不能排除动态路径的 ALE 离散、初始 `phi/Uf` 处理或 `correctPhi` 历史条件影响。

## 6. 已排除、未证明与下一步

### 已排除（本实验范围内）

1. 真实零运动参与者发出了非零位移：证据为 10 步全零输入及零 `pointDisplacement/cellDisplacement`。
2. 圆柱点或网格几何发生了可见运动：points SHA 全程相同，动态位移和 `meshPhi` 均为零。
3. 本次 preCICE Force 读取和求和本身不一致：参与者收到的 Force 与零组 OpenFOAM 总力逐步一致至约 `1e-12 N`。
4. Co 超过本实验的固定数值路径阈值：两组最大 Co 约 `0.346–0.350`；这不等于生产耦合的 Co/containment 资格已通过。

### 尚未证明

- 动态 `pcorr` 分支是否在当前 OF10/`displacementLaplacian` 配置下应与固定路径产生相同压力结果；
- `Uf/meshPhi` 的 oldTime 和 `correctPhi` 初始化是否具有当前短时路径所需的精确语义；
- 当前差异是否足以解释正式三切片中窗口 3 起的交替力放大；本实验只覆盖一个切片、零位移、10 步。

### 唯一最小下一步建议（仅规划）

在批准任何非零规定运动前，做一次同一 `PRECURSOR_STATE_V1` 起点、同一字典和同一 `dt` 的**动态网格但不接 preCICE 的零运动**对照，只改变“是否加载 adapter/preCICE”，并冻结首步 `cellDisplacement`、`pcorr`、`phi`、`p`、`U` 和 force 比较。该单因素实验可区分：

- A：差异由 OF10 动态/ALE/`pcorr` 路径本身产生；
- B：差异由 Adapter/preCICE function-object 生命周期或字段初始化产生。

本轮不执行该建议，不启动非零桥接；在人工审议前保持停止。

## 7. 证据状态与后续边界

本报告只新增 `_run_001`（测试 XML 配置失败）和 `_run_002`（有效但 FAIL_CLOSED）的索引与解析结果，不覆盖任何旧 runtime。W10 力身份重放、正式 0.05 s `FAIL_CLOSED`、窗口 9 的最后共同有效时间 `0.145 s`、Persistent `U/Uf oldTime` 指纹缺口均保持原结论。

下一步若要继续，必须先由人工选择上述单因素动态分支实验；在此之前不进入非零规定运动、自由 FSI、三切片连续耦合或长时间 VIV。
