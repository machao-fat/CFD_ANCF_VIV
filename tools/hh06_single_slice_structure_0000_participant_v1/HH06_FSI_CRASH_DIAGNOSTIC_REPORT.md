# HH06 单切片 FSI 崩溃只读诊断报告

## 1. 诊断范围

本报告针对 `/home/machao/OpenFOAM/coupling/singal_slice/slice0000` 的 HH06 单切片 50-window 重试记录。用户已要求停止 retry；本次仅读取已有日志、最后正常场和网格，不启动 OpenFOAM、preCICE、ANCF，也不创建新的 OpenFOAM 时间目录。

诊断状态：`DIAGNOSTIC_COMPLETE`  
最终资格状态：`DO_NOT_PASS`（50-window 生产前验证未完成）

截至报告生成时，残留进程检查未发现 `pimpleFoam`、`Structure_0000` participant 或 ANCF worker 进程。

## 2. 结论先行

| 分类 | 结论 | 证据 |
|---|---|---|
| A. turbulence 发散 | **主要原因，支持** | 30.0040 s 后 `k` 出现负值；30.0042 s `omega` 出现巨大正/负值，随后 Courant 数跃升 |
| D. pressure/GAMG 发散 | **次生原因，支持** | 异常 `omega/k` 和高 Co 后，GAMG pressure solve 在 `scale/Vcycle` 触发 `SIGFPE` |
| B. mesh motion 坏网格 | **当前证据不支持为首因** | 最新 mesh 检查通过；独立 mesh-only replay 通过，未见负体积证据 |
| C. rollback 状态不一致 | **流体场部分未能从现有证据排除** | 结构侧 checkpoint/rollback 有记录，但当前证据不能证明 OpenFOAM adapter 恢复了 `U/p/k/omega/nut/meshPhi/points` |

因此当前最准确的分类是：

`PRIMARY_TURBULENCE_RAS_DIVERGENCE`  +  `SECONDARY_PRESSURE_GAMG_FPE`  
`FLUID_ROLLBACK_FIELD_RESTORE_UNRESOLVED`  
`NOT_A_CONFIRMED_MESH_NEGATIVE_VOLUME_FAILURE`

这不是“已在 crash 时间点写出 NaN/Inf 场”的结论：崩溃时没有相应时间目录，不能直接读取 30.0042/30.0044 s 的完整字段。能确认的是日志中的非物理有限值和随后 FPE。

## 3. 重试结果

### RETRY7 / RETRY8 / RETRY10

三次都在约 `30.0042–30.0044 s` 附近进入同一模式：

```text
30.0038 s: Co max = 0.4258242566
30.0040 s: Co max = 1.497721095; bounding k min = -4.517129971e-13
30.0042 s: Co max = 21.04137642; bounding omega min = -142448.3008,
          max = 120771.218
30.0042 s: later omega max = 9.936783773e9, k min = -9.43608139e-7
30.0044 s: Co max = 14.38620211; bounding omega min = -1.155651408e9,
          max = 123013.8165; k min = -8.699802771e-7
```

RETRY8/10 的峰值略有差异，但失稳时间和机制重复。对应 stderr 均为：

```text
Foam::sigFpe::sigHandler
Foam::GAMGSolver::scale
Foam::GAMGSolver::Vcycle
Foam::GAMGSolver::solve
Foam::fvMatrix<double>::solveSegregated
... pimpleFoam
```

Fluid return code 为 `136`；participant 的 EOF 是流体进程退出后的下游结果，不是独立的 preCICE 根因。

### RETRY9

Aitken 配置在进入有效流体推进前即在 `libprecice.so` 中触发 SIGFPE，不能用来判断 CFD 场发散。

### RETRY11

RETRY11 是用户手动停止，不是新的 FPE 崩溃。preCICE iteration log 有 17 个时间窗记录：

- 到达/记录的时间窗：17；
- 只有第 2 个时间窗 `Convergence=1`；
- 其余 16 个达到 `max-iterations=20` 且 `Convergence=0`；
- 第 18 个时间窗在用户停止时进行到 participant `it 7`；
- 目标 50 个 accepted windows 未完成。

所以不能把 RETRY11 写成 17/50 成功或 50-window PASS。

## 4. 时间步与最后正常时间

当前合同中的 `deltaT = 0.0002 s`。已有可读物理时间目录只有 `30`；没有 `30.0038`、`30.0040`、`30.0042` 或 `30.0044` 的完整写出目录。因此：

- 最后可直接检查的完整场：`30`；
- crash-time fieldMinMax：不可直接获得；
- 不能据此声称 crash 时已经写出了 NaN/Inf 字段。

完整原始日志仍保留在 case 目录中，主要文件：

- `HH06_50W_RETRY7_FLUID.stdout`
- `HH06_50W_RETRY7_FLUID.stderr`
- `HH06_50W_RETRY8_FLUID.stdout`
- `HH06_50W_RETRY8_FLUID.stderr`
- `HH06_50W_RETRY10_FLUID.stdout`
- `HH06_50W_RETRY10_FLUID.stderr`
- `HH06_50W_RETRY11_FLUID.stdout`
- `precice-Fluid_0000-iterations.log`

本次读取的关键配置/证据 SHA256：

```text
precice-config.xml                  2c67b8628e428e3d53faa935574bba644a433749109120de34e0026c5ec95c76
system/fvSolution                   326a2195a56929008ca19bc1b4857600f742460ab798009d9812686997989e87
system/fvSchemes                   3c60f43d1cf67043e18f896c783302ca27d30ceb609abccb39f1642a8cf6508b
constant/dynamicMeshDict            56158d50b619174c67a343d2660c87c4c0c5e1370e2fde44a4a4c6f07c5ccdc5
HH06_50W_RETRY7_FLUID.stdout       2555710eadcd209b0c250d56f795c107099ecdab556b5bd8634a2cd16659e305
HH06_50W_RETRY7_PARTICIPANT.stdout 1daadc2bbb4277683a9544ef080c151871e24bba3efd974401de63bd5185f404
HH06_50W_RETRY11_FLUID.stdout      4397009035efa846cc615224caf39d1a2469e6859cff7540a1d807d9ff4a66fc
HH06_50W_RETRY11_PARTICIPANT.stdout 39b88d596c0a7271f486da12530b6f590f3dd9a6724bd5715f2c89b76c5ef5e2
```

查看 RETRY7 最后 200 行：

```bash
tail -n 200 HH06_50W_RETRY7_FLUID.stdout
tail -n 200 HH06_50W_RETRY7_FLUID.stderr
```

## 5. 最后正常时间 30 的字段范围

通过临时只读 VTK 导出检查后已删除临时 VTK 目录；原始 case 未写入新时间目录。时间 `30` 的字段范围为：

| 场 | 范围/结果 |
|---|---|
| `U` 分量 | x `[-0.196622, 0.553486]`; y `[-0.477866, 0.401697]`; z `[-1.25227e-19, 1.24933e-19]` |
| `|U|` | `[2.74286366495e-05, 0.55796811970]` |
| `p` | `[-0.143416, 0.0535786]` |
| `k` | `[2.70199e-10, 0.015897]` |
| `omega` | `[1.98359, 93792.8]` |
| `nut` | `[2.88081e-15, 0.000280314]` |
| 有限性 | 以上最后正常场检查未见 NaN/Inf |

注意：时间 30 的 `omega` 已有很大的上界，但仍是有限值；真正的负值和数量级爆炸出现在后续未写盘的内部时间步日志中。

## 6. 最后正常网格检查

对 `30` 运行 `checkMesh -latestTime -allGeometry -allTopology`，结果为 `Mesh OK`：

- points: `94498`
- cells: `46826`，全部 hexahedra
- min volume: `7.687364982e-10`
- max volume: `1.289596521e-05`
- total volume: `0.01973956178`
- max aspect ratio: `25.86850031`
- max non-orthogonality: `44.00486412 deg`
- average non-orthogonality: `8.719722714 deg`
- max skewness: `0.8545162319`
- cell determinant minimum: `0.01401508753`
- failed faces / topology / geometry checks: none

独立 mesh-only replay 也通过，历史证据中的 min volume 约为 `7.687364982e-10`、max non-orthogonality `44.00486412 deg`、max skewness `0.8545162319`。这些证据不支持“首先由负体积或 checkMesh 失败触发”。

## 7. 动网格与 retry 审计

当前 `constant/dynamicMeshDict` 使用：

```text
motionSolver displacementLaplacian;
diffusivity quadratic inverseDistance 1(cylinder);
```

preCICE 是 parallel-implicit，当前 RETRY11 使用 constant relaxation `0.2`，最大耦合迭代 `20`；此前 RETRY7/8/10 使用过其他 relaxation/solver relaxation 组合。当前 RETRY11 停止后配置保留在停止时状态，未自动回滚；备份文件仍在 case 目录。

结构侧 participant 的 retry 语义是：收到 checkpoint 请求时保存结构物理状态，收到 rollback 请求时恢复 `q/qdot/qddot` 等结构状态，transport counters 保持单调。该证据只覆盖 Structure side。

OpenFOAM 的 `U/p/k/omega/nut/meshPhi/points` 恢复由编译的 `libpreciceAdapterFunctionObject.so` 负责。当前仓库 Python 代码和日志没有给出足够证据证明每次 fluid retry 都完整恢复了这些流体/ALE/turbulence 状态，也没有证据表明 retry 时重新初始化 turbulence。故 C 类只能标为：

`FLUID_ROLLBACK_FIELD_RESTORE_UNRESOLVED`

而不能写成已确认的 rollback 根因。

## 8. 结论与停止边界

本轮已经停止，不再 retry。没有启动新的 CFD、preCICE 或 ANCF 物理推进，也没有创建新的 OpenFOAM 时间目录。

当前最小诊断结论是：

1. 首次可见异常是 RAS/turbulence 场发散（`omega` 先出现负值和极大正值，`k` 随后变负）；
2. Courant 数在同一时间段从约 `1.50` 跃升到 `21.04`，随后约 `14.39`；
3. GAMG pressure FPE 是失稳后的次生故障；
4. 最后正常网格检查通过，当前证据不足以把 mesh motion 定为首因；
5. fluid rollback 的 turbulence/ALE 字段恢复仍是未审计项；
6. RETRY11 是用户停止且未达到 50-window 目标，不能算通过。

后续若要继续，必须先由人工授权针对“OpenFOAM adapter 是否在 implicit retry 中恢复全部 fluid/ALE/turbulence 状态”做独立审计；本报告不自动修改参数、不自动续算。
