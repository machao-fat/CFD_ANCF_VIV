# STRICT_SAME_FVSOLUTION_NO_ADAPTER_PROBE_V1

日期：2026-09-09  
范围：`OF 0.100 -> 0.105 s`，`dt=0.005 s`，一次动态零位移步，无 ANCF、无非零运动、无第二次 CFD 运行。

## 结论摘要

本轮只修复了 test-only harness 的 Python 兼容性错误并执行了一次无 Adapter 动态零运动 probe。OpenFOAM 进程正常结束，写出 `0.105` 场和力文件；这证明的是 **runtime execution**，不是固定网格—动态网格力一致性 PASS。

关键观察：

1. 无 Adapter 动态组与已有真实 preCICE zero 组在 `0.100` 起点及 `0.105` 输出上逐字节一致；`U/p/phi/pointDisplacement/cellDisplacement/meshPhi/Uf` 的结构化只读解析也一致。`.105` 总力均为 `Fx=1248.2039243949 N, Fy=-45.965786437332 N`。
2. 二者与固定网格组的 `0.105` 力不同：固定组 `Fx=1320.4779224812 N, Fy=-8.157110925055 N`，动态差值为 `(-72.2739980863, -37.808675512277) N`。动态组的点位移、单元位移和 `meshPhi` 均为零，仍执行了动态 mesh/ALE/通量校正路径。
3. 但是，本次 probe 实际使用的 OF10 核心前缀不是已有真实 preCICE zero runtime 的同一二进制前缀：无 Adapter 运行使用 `.../of10_owned_atomic_mesh_history_restore_prototype_v1/openfoam10`，而真实 zero 使用 `.../owner_diagnostic_abi_build_001/openfoam10`。`libOpenFOAM.so` 相同，但 `pimpleFoam` 与 `libfiniteVolume.so` SHA 不同。因此严格“唯一改变因素为移除 Adapter/preCICE”的二进制隔离条件没有完全成立。

据此，本轮结论为：

```text
NO_ADAPTER_PROBE_RUNTIME = PASS
STRICT_SAME_FVSOLUTION_NO_ADAPTER_PROBE = NOT_EVALUABLE_AS_PURE_SINGLE_FACTOR
ADAPTER_AS_PRIMARY_CAUSE = NOT_SUPPORTED_BY_EXISTING_EVIDENCE
CAUSE_CLASS = DYNAMIC_ALE_FLUX_CORRECTION_WITH_UNRESOLVED_INITIAL_FLUX_COMPATIBILITY
LOCAL_FIXED_ZERO_BRIDGE = FAIL_CLOSED
NEXT_NONZERO_PRESCRIBED_BRIDGE = NOT_AUTHORIZED_PENDING_REVIEW
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

历史 `_run_003` setup 失败、既有 `LOCAL_FIXED_ZERO_BRIDGE=FAIL_CLOSED` 及所有旧 runtime 保持不变。

## 1. Harness 修复与运行边界

原始目录：

`runtime/cfd_current_fixed_zero_bridge_v1_run_003_no_adapter_dynamic_one_step`

保留的 `setup_failure.txt` 记录 `Path.write_text(..., newline=...)` 在当前 Python API 中不支持，且 `solver_started=false`。本轮只将 test-only 写文件辅助函数改为显式 `path.open(..., newline="\n")`，并将新结果隔离到 `_run_004`；未修改 OF10、Adapter、preCICE、网格或数值设置。

执行脚本：

`tools/cfd_current_fixed_zero_bridge_v1/run_no_adapter_dynamic_probe.py`

运行结果：

`results/cfd_current_fixed_zero_bridge_v1_run_004_no_adapter_dynamic_one_step/probe_result.json`

`return_code=0`，`target_time_written=true`，stdout 以 `End` 结束，`adapter_loaded=false`。本轮只启动该一次 CFD 进程；后续比较器为离线文件读取，没有启动求解器。

## 2. 输入身份与二进制闭包

无 Adapter case 与真实 zero case 的以下输入 SHA 完全一致：

| 输入 | SHA256（两组相同） |
|---|---|
| `system/fvSolution` | `981465e887c0ae1c6e5d6a7cd6277c08ecfc01fee188c7387b81f74ceb3ab7ef` |
| `system/fvSchemes` | `8dde725a7774d93a6ad1203b88f8fcc8eed5c87d1f155cad91716c079c9c4f26` |
| `constant/dynamicMeshDict` | `ba36127272da53fe36ef7ad8eb6d8534a810d13eb95b7d48b8967970aca7333e` |
| `constant/physicalProperties` | `0d3de0742557cc51bbf91260badefd0c926c93c1a36a61e73aecb7b4e2383186` |
| `constant/momentumTransport` | `6a59c07e6d58299452051245f3bfa1e196237d35d5af0d0a58eb046979400b192` |
| `constant/polyMesh/points` | `fbdbb5f484af3b11e025dbeba34ac41459cb3cf08bf5544c561e16a77149012f` |
| `0.1/U` | `dd5fd46606bb82a0cfb9a56a282e737f3c9a3cb1c1eebac53b9579da4688b4ac` |
| `0.1/p` | `88ff50b56477b4e38f7921672ab2820137305cae2a40ad754e38817cdc7710a9` |
| `0.1/phi` | `9bfb8d3d1342f8934e4a18dd00d5f4b58ef1d3f4e630c8933b19ffe56a35ff5a` |

（比较器保存的规范小写值见 JSON。）

无 Adapter 实际加载的 solver：

```text
realpath = /home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam
SHA256  = deebe14e05e1342c984db377c11979553a1fe44296ae0b6406501cac45b2288e
Build   = 10-c4cf895ad8fa
```

在该 prefix 的 `LD_LIBRARY_PATH` 下，`ldd` 将 `libOpenFOAM.so`、`libfiniteVolume.so`、`libdynamicMesh.so`、`libmeshTools.so`、`libPstream.so` 等解析到同一 `openfoam10/platforms/linux64GccDPInt32Opt/lib`（`libPstream` 为其 `openmpi-system` 子目录），系统 MPI/标准 C++ 运行库来自 `/usr/lib/x86_64-linux-gnu`。

严格性限制：真实 preCICE zero 的 launcher 使用：

```text
/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10
```

真实 zero 还加载已冻结 Adapter build `c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17`；无 Adapter probe 明确不加载该库。

其关键 SHA 为：

| 文件 | no-Adapter prefix | real preCICE zero prefix |
|---|---:|---:|
| `pimpleFoam` | `deebe14e05e1342c984db377c11979553a1fe44296ae0b6406501cac45b2288e` | `c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43` |
| `libOpenFOAM.so` | `a34df8ad17f8250071c697d150e593563f2152c194b87fdb906b7a6493f37cde` | `a34df8ad17f8250071c697d150e593563f2152c194b87fdb906b7a6493f37cde` |
| `libfiniteVolume.so` | `50c251483d65cbf1f617990e39e12a9fbed1434ac419d8d2996ec1d3d5ba8a6e` | `5a820734c0a61a8bd6cdb730d95a651e002848d9d9d4d8a4897ea42608a2e48e` |

这是本轮不能把输出相等直接升级成纯 Adapter 单因素 PASS 的原因。该限制不改写已有历史证据，只限制本轮新 probe 的标签。

## 3. 完整字段与力比较

比较器：

`tools/cfd_current_fixed_zero_bridge_v1/inspect_strict_probe.py`

输出：

`results/cfd_current_fixed_zero_bridge_v1_run_004_no_adapter_dynamic_one_step/strict_probe_comparison.json`

它只解析已经写出的 OpenFOAM 字段和 `forces.dat`，并复用结构化 parser；不调用 `oldTime()`、`Uf()`、`meshPhi()` getter，不构造 OpenFOAM 对象。

### 3.1 初始时刻

固定、真实 zero、无 Adapter 三组 `0.100` 的 `U/p/phi` SHA 和 internal/boundary 结构化值相同。可靠 parser 读到：

- `U`: `16244` 个内部 vector（`48732` 分量）；
- `p`: `16244` 个内部 scalar；
- `phi`: `24226` 个内部 scalar；
- 初始 `phi` internal value hash 为 `e9f042a69e1d0a98c343410ab566d0b1f2524cf12871b61874c9ae79aed38ad9`。

三组起点没有 `0.1/Uf` 文件；动态 OF10 路径按源码在内存中由 `fvc::interpolate(U)` 创建 `Uf`，不能把磁盘缺失误判为错误。

### 3.2 `.105` 动态输出

无 Adapter 与真实 zero 的以下字段逐字节且结构化相等：

| 字段 | SHA256（两组相同） | 关键数值 |
|---|---|---|
| `U` | `c16b52c21390aa47b53de493a1c09008d255c06d931bd4675a37333a4b9cc2e5` | internal max abs `1.71444695896` |
| `p` | `dd9c69f4f44eeb5864f7ac12d95231ea7b835ed19f7459aa1802c4b2ffb35b04` | internal max abs `1.35757914813` |
| `phi` | `68c37f183a6637d2b1657fd7cbc7c6ef10e3406e0e32062b4a82a93632870cd5` | internal max abs `0.638437181454` |
| `pointDisplacement` | `cc0ece052830fdd20131dfa96fcf2106d97f9b9f23129dd19802958283c15d02` | internal/boundary zero |
| `cellDisplacement` | `1355c73b4d9aa076ad72396e071e7526b7919d0f41e58f1873edd07363a76da7` | internal/boundary zero |
| `meshPhi` | `47ce1a6c6a412dcb95df81436b9c97a6e0a037c76402800cb044c6de1f7daf11` | internal/boundary zero |
| `Uf` | `8c9a1bb962ad5bb37483ff59f7777b00e845f9f5e56d42ad80284f693f34bdb0` | `24226` face vectors, max abs `1.70264047442` |

### 3.3 力

`.105` 的无 Adapter 与真实 zero 完全相同：

```text
pressure = (542.6167070165, -47.2938883278, 9.25178003649e-17) N
viscous  = (705.5872173784,   1.32810189047, -2.45847656084e-17) N
total    = (1248.2039243949, -45.965786437332, 6.79330347564e-17) N
```

固定组同一时间层：

```text
total    = (1320.4779224812, -8.157110925055, 6.95667289605e-17) N
```

因此固定—动态首步差异主要体现在压力力（`Δpressure=(-75.2181244884,-37.530854132055) N`），黏性力差为 `(2.9441264021,-0.277821380222) N`。

## 4. 实际 OF10 顺序与通量相容性

独立 OF10 源码和无 Adapter stdout 支持以下顺序：

`createPhi (READ_IF_PRESENT) → dynamic createUfIfPresent (READ_IF_PRESENT; absent, interpolate U) → mesh.update/motionSolver → mesh.movePoints → create/refresh meshPhi → correctPhi/pcorr → UEqn → pEqn → correctUf/makeRelative`。

无 Adapter `.105` 日志的关键数值：

```text
cellDisplacement x/y: initial=0, final=0, iterations=0
pcorr: initial=1, final=0.00469713118572, iterations=3
first continuity global = 1.98763663389e-11
Ux final residual = 7.58659172494e-10
Uy final residual = 4.19050615162e-10
first p final residual = 0.00388440964083
second p final residual = 5.63496486627e-09
final continuity global = 5.67289272814e-15
```

这说明：零运动不等于固定路径跳过动态通量校正；`pcorr` 是中间 CorrectPhi 残差，不是最终压力方程残差。当前证据尚没有 `CorrectPhi` 前后内存态的无副作用指纹，因此不能证明 persisted `phi` 与动态新建 `Uf` 在校正前已达到目标数值相容性，也不能据此判定 OF10 实现缺陷。

## 5. 因果判定

### 已证明

- 起点 `U/p/phi` 不是首步差异来源；完整 internalField 与 value-backed boundaryField 已结构化复核。
- 零位移动态路径确实创建 `Uf` 并执行动态 move/CorrectPhi；点位移、cellDisplacement、meshPhi 写出值为零。
- 无 Adapter 运行的写出结果与真实 zero 运行逐字段、逐力完全相同（在二进制前缀差异限制下）。
- 固定路径与动态路径的首个差异位于动态/ALE/CorrectPhi 分支；不能将 `pcorr` 中间残差直接认定为最终 PIMPLE 失败。

### 尚未证明

- `phi` 与由 `U` 重建的 `Uf` 在 CorrectPhi 前的面通量是否逐面相容；本轮没有添加内存 before/after 诊断。
- 动态首步的力差是否在论文所需物理精度内可接受；现有严格力 gate 仍为 FAIL_CLOSED。
- 由于 OF10 prefix 不同，本轮无 Adapter 输出相等不能作为完全纯粹的单因素因果证明。

### 不支持的假设

- 零运动 participant 注入了非零位移：`.105` 输入和点/单元位移均为零。
- Adapter function-object 单独制造了该首步差异：现有真实 zero 与无 Adapter 输出一致，且历史无 Adapter 动态 runtime 也复现了该路径；但严格二进制同构隔离尚未完成。
- `pcorr` 中间 residual 等于最终求解失败：最终 p residual 和 continuity 继续收敛，stdout 以 `End` 结束。

## 6. 决策与下一步

本轮不修改 `correctPhi`、PIMPLE、物性、初始场、dt、网格或生产代码；不关闭 CorrectPhi，不放宽容差，不自动补跑第二个实验。

最小后续动作（需人工批准）是：使用真实 preCICE zero 所用的 `owner_diagnostic_abi_build_001` OF10 prefix，重新建立同一 no-Adapter 单步，以消除本轮唯一的二进制混杂因素；这不是本轮自动执行的第二次实验。若该条件不再需要，可将现有结果作为“动态路径与 Adapter 输出一致的支持性证据”，但仍不能把固定—动态力差称为数值 PASS。

因此非零规定运动桥接仍不授权。`Persistent U/Uf oldTime` 指纹缺口继续独立记录，不归因于本轮首步力差。

## 7. 证据索引

- 成功 probe：`runtime/cfd_current_fixed_zero_bridge_v1_run_004_no_adapter_dynamic_one_step`
- 成功结果：`results/cfd_current_fixed_zero_bridge_v1_run_004_no_adapter_dynamic_one_step/probe_result.json`
- 只读逐字段/逐力比较：`results/cfd_current_fixed_zero_bridge_v1_run_004_no_adapter_dynamic_one_step/strict_probe_comparison.json`
- 离线比较器：`tools/cfd_current_fixed_zero_bridge_v1/inspect_strict_probe.py`
- 可靠 OpenFOAM 字段解析器：`tools/cfd_current_fixed_zero_bridge_v1/inspect_openfoam_fields.py`
- 历史 setup FAIL：`runtime/cfd_current_fixed_zero_bridge_v1_run_003_no_adapter_dynamic_one_step/setup_failure.txt`
- 既有固定—真实 zero 报告：`docs/cfd_current_fixed_zero_bridge_v1/CFD_CURRENT_FIXED_ZERO_CORRECTION_CAUSAL_REVIEW_V1.md`
