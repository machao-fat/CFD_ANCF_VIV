# COMPATIBLE_UF_COUNTERFACTUAL_V1

日期：2026-09-09
范围：一次诊断反事实初值实验；仅运行当前动态零运动 `0.100 → 0.105 s` 一步。不重复 Adapter/no-Adapter 隔离，不修改生产源码、Adapter、`U/p/phi`、网格、PIMPLE、dt 或物性。

## 结论

在隔离 case 中，以 `fvc::interpolate(U)` 为切向速度基准，仅沿每个面法向调整 `Uf`，使 `Sf·Uf` 与持久 `phi` 相容。构造后全场通量误差为：

```text
count   = 24506
max_abs = 1.1102230246251565e-16
L2      = 4.134237799927448e-15
```

唯一授权的 `0.100 → 0.105 s` 动态零运动步正常完成。与已有真实 zero 结果相比：

- `CorrectPhi` 前的 `phi`/`Sf·Uf` 不相容从 `5.18088056584295e-03` 降至 `2.80242495875882e-12`。
- `persisted phi` 与局部 CorrectPhi 后结果的差异从 `7.15474414826950e-04` 降至 `8.88206552751569e-08`。
- 新测试总力为 `(1320.477922503, -8.157110921172) N`；已有真实 zero 总力为 `(1248.2039243949, -45.96578643733) N`，差异为 `(+72.2739981081,+37.8086755162) N`。
- 新测试与已有固定网格参考总力 `(1320.4779224812,-8.157110925055) N` 的差异仅约 `(2.2e-8,3.9e-9) N`。

这支持：**初始 `Uf` 重建/通量投影是当前首步固定—动态压力力差的主要启动来源。** 这不是对三切片长期放大、附加质量不稳定或 VIV 物理机制的证明；不授权进一步耦合运行。

状态保持：

```text
LOCAL_FIXED_ZERO_BRIDGE = FAIL_CLOSED
NEXT_NONZERO_PRESCRIBED_BRIDGE = NOT_AUTHORIZED_PENDING_REVIEW
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```

## 1. 反事实初值构造

隔离 case：

`runtime/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/case`

保留真实 zero 的 `0.100 s` `U/p/phi`、expanded-medium 网格、`dynamicMeshDict`、`fvSchemes`、`fvSolution` 和物性。只新增 `0.1/Uf`，不改写原始 `U/p/phi`。

构造程序：

`tools/cfd_current_fixed_zero_bridge_v1/compatible_uf_initializer/compatibleUfInitializer.C`

对每个内部或边界面采用：

```text
Uf_new = Uf_interpolated + Sf * (phi - Sf·Uf_interpolated) / |Sf|²
```

因此仅改变法向分量，保留 `fvc::interpolate(U)` 的切向分量和其真实 patch 类型。实际写出的 patch 类型为：

```text
front/back: empty
lower/upper: symmetryPlane
inlet/outlet/cylinder: calculated
```

构造前误差为 `max_abs=5.180880565842955e-03`、`L2=1.6606630267160766e-02`；构造后误差为上面的机器精度水平。`U/p/phi` 的初始结构化值和 SHA 与已有 fixed/zero 起点一致。

## 2. ABI 与运行身份

运行使用真实 zero 所用的 owner-diagnostic OF10 前缀：

`/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10`

Foundation 构建：`10-c4cf895ad8fa`。

| 二进制/库 | SHA256 |
|---|---|
| `pimpleFoam` | `c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43` |
| `compatibleUfInitializer` | `618b4e8770872a9347c694b6ea082f1cd45cd7279ade46210445abc4e9295011` |
| `libOpenFOAM.so` | `a34df8ad17f8250071c697d150e593563f2152c194b87fdb906b7a6493f37cde` |
| `libfiniteVolume.so` | `5a820734c0a61a8bd6cdb730d95a651e002848d9d9d4d8a4897ea42608a2e48e` |
| `libfvMeshMovers.so` | `da199da31b42a7b5e07248864cb91c6556dba0afa4db74507879f4124d307e78` |
| `libfvMotionSolvers.so` | `debc2c86635805c616874612c9c361477424ec58cba77ccc46853b786750eb30` |

运行时依赖闭包全部来自该 OF10 前缀及系统 MPI/C++ 库；无 `ldd -r` 未解析项。生成的初始 `Uf` SHA256：

`03bd0deacf48d01fa7db5902eab9ad19a237f153bdc9907c1f96e5d1b41d2ee8`

## 3. CorrectPhi 对照

### 原始真实 zero

已有只读诊断测得：

```text
persisted phi - Sf·Uf: max_abs=5.18088056584295e-03, L2=1.66066302671608e-02
persisted phi - corrected phi: max_abs=7.15474414826950e-04, L2=2.79691027116373e-03
reconstructed div: max_abs=4.50766807167410, L2=11.7289976191596
corrected div: max_abs=1.32088960193799e-02, L2=4.59552911769231e-02
```

运行时 `pcorr` 为 `0.00469713118572`，3 次迭代。

### 相容 `Uf` 反事实

```text
persisted phi - Sf·Uf: max_abs=2.80242495875882e-12, L2=9.40636187668129e-11
persisted phi - corrected phi: max_abs=8.88206552751569e-08, L2=2.61744504417335e-07
reconstructed div: max_abs=3.86478956165782e-10, L2=4.40469670254885e-09
corrected div: max_abs=5.87185170165949e-10, L2=4.32672088955501e-09
```

该 probe 的 `pcorr` 为 `0.00590652540726`，4 次迭代。因而 `pcorr` 的归一化终端残差/迭代数并不是“校正幅度”的单调指标；本报告以逐面 `phi` 差异和散度作为初值相容性指标。

## 4. 唯一一次 CFD 单步

运行目录：

`runtime/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1`

实际运行结果：`return_code=0`，stdout 以 `End` 结束，时间推进仅为 `0.100 → 0.105 s`。动态零运动的 `meshPhi`、`pointDisplacement` 和 `cellDisplacement` 仍为零。

关键数值：

```text
Co mean/max = 0.03019056182 / 0.350303474526
final continuity global = 1.30236365687e-15
final continuity cumulative = 2.60698349762e-12
```

`0.105` 力对照如下（单位 N）：

| 组 | pressure (Fx,Fy) | viscous (Fx,Fy) | total (Fx,Fy) |
|---|---:|---:|---:|
| 已有真实 zero | `(542.6167070165,-47.2938883278)` | `(705.5872173784,1.32810189047)` | `(1248.2039243949,-45.96578643733)` |
| 相容 `Uf` 反事实 | `(617.8348315266,-9.763034191641)` | `(702.6430909764,1.605923270469)` | `(1320.477922503,-8.157110921172)` |
| 已有固定网格参考 | `(617.8348315049,-9.763034195745)` | `(702.6430909763,1.605923270690)` | `(1320.4779224812,-8.157110925055)` |

结构化字段比较显示，相容 `Uf` 的最终内部场相对固定参考的差异为：

```text
U:   max_abs=1.00000008274037e-11, L2=3.28874877887559e-10
p:   max_abs=4.76299999441210e-10, L2=1.31151270717415e-08
phi: max_abs=2.00001126771099e-12, L2=7.19653505454891e-11
```

而相对原始动态 zero 的差异分别为 `U=2.249636676e-02`、`p=2.87780343055e-01`、`phi=5.31824344271e-04`（内部场 max abs）。这说明相容初值改变了动态首步的压力/速度演化，而不是只改变输出力文件。

## 5. 因果判定与边界

### 支持的结论

- 在当前一个动态零运动步内，初始 `Uf`/通量不相容足以产生原始动态 zero 的压力力偏差。
- 使初始 `Sf·Uf` 与持久 `phi` 相容后，首步力恢复到固定网格参考，原始约 `72.274 N` streamwise 和 `37.809 N` transverse 差异基本消失。
- 该结果不支持把 Adapter 作为首步差异的主要来源；本实验没有改变 Adapter，因为本实验本身不加载 Adapter。

### 未证明的内容

- 不能由一个零运动单步推出三切片自由耦合长期力放大、附加质量不稳定或 VIV 物理成因。
- 不能把诊断反事实 `Uf` 冒充为原生历史场，也不能将其直接用于生产。
- `LOCAL_FIXED_ZERO_BRIDGE` 历史 FAIL、W10/0.05 s FAIL 和 `Persistent U/Uf oldTime` 独立资格缺口均保持不变。

## 6. 停止与后续建议

本轮已达到授权范围并停止。当前不启动非零规定运动、三切片 0.05 s 或长时间 VIV。

若人工继续批准，下一项最小实验应在同一 CFD 基线下比较原生 `interpolatingSolidBody` 与当前 `displacementLaplacian/preCICE` 的非零规定运动；应预先固定运动公式、边界、网格通量、力相位和容差。不得将本反事实 `Uf` 写入生产配置。

## 7. 证据索引

- 初值构造 JSON：`results/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/initializer.json`
- 相容性静态 probe：`results/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/compatibility_probe_static.json`
- 相容性动态本地 probe：`results/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/compatibility_probe_moved.json`
- 字段结构化比较：`results/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/field_comparison.json`
- CFD stdout/stderr：`runtime/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/fluid.stdout`、`fluid.stderr`
- 反事实 case：`runtime/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/case`
- 构造程序：`tools/cfd_current_fixed_zero_bridge_v1/compatible_uf_initializer/compatibleUfInitializer.C`
- 字段比较程序：`tools/cfd_current_fixed_zero_bridge_v1/compare_counterfactual_fields.py`
- 通量 probe：`tools/cfd_current_fixed_zero_bridge_v1/phi_compatibility_probe/phiCompatibilityProbe.C`
