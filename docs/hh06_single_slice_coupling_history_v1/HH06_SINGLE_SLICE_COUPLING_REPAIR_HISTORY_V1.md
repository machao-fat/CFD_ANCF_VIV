# HH06 单切片耦合问题与修复全过程归档

**归档版本：** `HH06_SINGLE_SLICE_COUPLING_REPAIR_HISTORY_V1`
**归档日期：** 2026-09-22
**目标算例：** `/home/machao/OpenFOAM/coupling/singal_slice/slice0000`
**研究对象：** HH06 Case 1，高 Re 单切片 Fluid_0000–preCICE–Structure_0000–ANCF

## 1. 范围和最终结论

本文件把 HH06 单切片从合同准备、SHM1 协议、Structure_0000 wrapper、离线
worker、preCICE 初始化、checkpoint/rollback、ALE 位移读路径，到 25-window
有界资格测试和 worker lineage 修复的证据串成一条时间线。

最终状态不是“生产 FSI 已通过”：

- 结构端 SHM1、物理 rollback、transport ID、preCICE 一窗口 handshake 和
  非零 ALE 一窗口隔离资格均已有 PASS 证据；
- 25-window bounded qualification 的 force unit chain、rollback、checkpoint、
  transport ID 均通过，但后期出现 ALE/流体/湍流 runaway；
- 因此 `HH06_BOUNDED_MULTIWINDOW_ALE_QUALIFICATION = DO_NOT_PASS`；
- 最新 worker lineage parity 修复只在隔离 worker 上通过，尚未部署到
  `slice0000`，也没有重新启动 CFD。

这份归档不把任何失败资格测试改写成成功，也不把诊断位移当作 HH06 物理结果。

## 2. 冻结的物理和接口合同

| 项目 | 冻结值 |
|---|---:|
| 结构长度 `L` | 13.12 m |
| 圆柱直径 `D` | 0.028 m |
| 来流 `U` | 0.31 m/s |
| 密度 `rho` | 1000 kg/m³ |
| 运动黏度 `nu` | 1.1388087116e-6 m²/s |
| Reynolds 数 | 约 7622 |
| ANCF 元素数 `Ne` | 32 |
| ANCF 节点数 | 33 |
| ANCF DOF | 198 |
| 代表单切片位置 | `s = 2.97 m` |
| 代表条带长度 | `DeltaL = 1.98 m` |
| CFD restart | 30 s |
| 耦合步长 | 0.0002 s |
| benchmark top tension | 1175 N |
| equilibrium reaction tension | 1188.28 N |
| SHM1 region | 0–13.12 m |
| SHM1 added mass | [0.616, 0.616, 0] kg/m |
| SHM1 damping | [0, 0, 0] |

接口始终保持：

```text
OpenFOAM wall integration
  -> per-unit-span normalization (/0.028)
  -> strip resultant (*1.98)
  -> Fluid-Mesh Force
  -> Structure-Mesh single-point Force
  -> ANCF generalized load

ANCF section displacement at s=2.97 m
  -> Structure-Mesh single-point absolute Displacement
  -> Fluid-Mesh Displacement
  -> OpenFOAM pointDisplacement/cellDisplacement
  -> ALE mesh motion
```

禁止 CFD face 与 ANCF node 一一对应；结构端只接收一个合力点，ANCF 内部再做
广义载荷装配。

## 3. 按时间顺序的问题与修复

### 3.1 合同阶段：缺少 Structure_0000

**问题：** 初始 HH06 runtime 只有流体准备，结构侧 participant entry 缺失，
且早期合同容易把 CFD wall faces 误认为 ANCF nodes。

**处理：** 冻结 P1 `REF_NE32` 结构合同；定义一个 `Structure_0000` wrapper，
复用 `PreciceStructureFleetBackend`、`GenericStructuralCoordinator` 和 persistent
ANCF worker。Structure mesh 只暴露一个 `s=2.97 m` coupling point。

**结果：** `READY_FOR_DRY_RUN`，没有修改 ANCF kernel，也没有启动计算。

### 3.2 benchmark tension 与静态反力冲突

**问题：** HH06 benchmark 输入张力 1175 N 与 P1 静态平衡后的反力 1188.28 N
不同，若混写会改变物理合同。

**修复：** 合同分开记录：

- `benchmark_top_tension = 1175 N`：文献输入；
- `equilibrium_reaction_tension = 1188.28 N`：ANCF 静态平衡诊断反力。

1188.28 N 没有被替换写入 HH06 输入。

### 3.3 SHM1 协议与 worker identity

**问题：** Python 已实现 SHM1 codec，但最初无法证明运行时实际 binary 具备
SHM1 v1；协议资格因此 `DO_NOT_PASS`。

**修复链：**

1. 审计 C++ SHM1 marker/version、字段顺序和 trailer 顺序；
2. Python 增加 SHM1 marker `0x314D4853`、version 1、region validation 和
   `base -> SPX1 -> BLS1 -> SLD1 -> SHM1 -> DMP1` 序列化；
3. 冻结同一 git source baseline，使用正式 CMake/GCC 构建新的 qualified worker；
4. 用 production `KernelModel`/`KernelStepRequest` 构造 HH06 region，做 C++
   parse、SHM1+DMP1 和空 region legacy compatibility qualification。

**结果：** qualified worker SHA256 为
`69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF`。
旧 worker 没有被覆盖。

### 3.4 离线 runtime：transport ID 在 rollback 后复用

**问题：** 物理状态 rollback 已通过，但 backend checkpoint 同时保存了
`attempted_advance_count`，恢复后 Python 重新生成相同的 sequence/request/transaction
ID；C++ worker 的 duplicate-ID 检查正确拒绝了 replay。

**修复：** 只允许物理/solver state 进入 checkpoint；transport counters 改为
session-monotonic，rollback 只恢复 `q/qdot/qddot` 和 tentative state，不回退
通信身份。

**验证：** Trial A、rollback、Trial B 使用同一 physical window identity，但 B
拿到新 transport IDs；离线 runtime qualification PASS。

### 3.5 preCICE 初始化：Displacement initial data 缺失

**问题：** XML 声明 `Displacement initialize="yes"`，但 Structure participant
在 `Participant.initialize()` 前没有写初始位移。

**修复：** `initialize()` 中先读取 P1 `q0` 在 `s=2.97 m` 的 section displacement，
只写一个 Structure mesh coupling point 的绝对 `(x,y)`，再调用 preCICE initialize。

**验证：** one-window Fluid_0000–Structure_0000 handshake PASS；没有把 198 个
ANCF DOF 直接发送给 preCICE。

### 3.6 50-window preproduction：checkpoint 生命周期错误

**问题：** 第一个 50-window 尝试接受了两个窗口，第三个窗口发生多次 retry 后
报 `CheckpointError: no active checkpoint`。`GenericStructuralCoordinator.rollback()`
第一次 rollback 后把 active checkpoint 清空，违反 parallel-implicit 同一窗口可以
多次 rollback 的语义。

**修复：** rollback 恢复物理状态但保留 active checkpoint；只有 accepted `commit()`
才清除 checkpoint。增加 rollback once、rollback twice、rollback→retry→commit
测试。

**验证：** Python checkpoint lifecycle 3/3 PASS，既有 orchestration/adapter 测试
保持通过。原失败 50-window 证据保留，未伪造为成功。

### 3.7 25-window 前置 gate：force unit chain

**结果：** force unit chain PASS，缩放严格为：

```text
F_slice = F_raw / 0.028 * 1.98
factor = 70.71428571428571
```

最大闭合误差 0 N；没有额外重复乘 0.028 或 1.98。

### 3.8 25-window bounded qualification：后期 ALE/流体 runaway

**执行结果：** 25/25 accepted windows，25 次 rollback，force chain、物理状态、
Fluid fields、transport IDs 和 ANCF Newton 均通过；但后期数值响应急剧放大：

| 指标 | 最大值 |
|---|---:|
| OpenFOAM Co max | 184.662 |
| mesh Co max | 58.752 |
| mesh velocity max | 18.117 m/s |
| `max|U|` | 392.274 m/s |
| `omega_max` | 925092.97 |
| max applied strip force | 149994.84 N |

历史失败区间表现为 force/absolute displacement change 增大，随后 mesh velocity、
mesh Co、流速和 `omega` 一起增长。所有场在有界结束前仍是 finite，且没有负体积，
但这不满足数值健康要求。

**判定：** `DO_NOT_PASS`, blocker 为
`LATE_WINDOW_ALE_FLOW_TURBULENCE_RUNAWAY`。没有通过调 dt、松弛、湍流模型或
solver 参数来掩盖问题。

### 3.9 Fluid rollback fingerprint 审计

**发现：** 在隔离一窗口诊断中，`points/oldPoints/U/p/phi/k/omega/nut/`
`pointDisplacement/cellDisplacement` rollback hash 一致；但 checkpoint-write 时
`meshPhi` 尚未可观测，因此不能宣称完整 mesh-flux rollback 已证实。

**意义：** 该审计证明了大量字段恢复正确，但没有替代非零 ALE motion 审计，也没有
证明 production adapter binary 身份完全等同于诊断 build。

### 3.10 Displacement read path 断点

**问题：** preCICE Displacement registration、mapping 和 Structure 输出均 PASS，
但 OpenFOAM adapter 的 `Adapter::execute()` 没有调用 `readCouplingData()`；因此
`pointDisplacement/cellDisplacement/points/meshPhi` 不变化，ALE 没有被真正激励。

**设计结论：**

```text
fluid solve
 -> write Force
 -> preCICE advance
 -> read/write checkpoint as requested
 -> readCouplingData()
 -> next OpenFOAM fluid solve and normal mesh motion
```

初始化路径还必须是 `preCICE initialize() -> readCouplingData(0.0)`。
`FSI::Displacement::read()` 只负责把数据写入 displacement fields，不负责调用
`mesh.update()`/`movePoints()`；真正的 mesh motion 由下一次 OpenFOAM 生命周期触发。

### 3.11 隔离 adapter read-path 修复与非零 ALE 一窗口验证

**修复：** 只在隔离 adapter source 中加入初始化读、advance/checkpoint 后读、完整
point/oldPoints/mesh history restore 和 `meshPhi` 初始零值等处理，未覆盖 production
adapter。

**验证：** nonzero diagnostic displacement 进入 Fluid，`pointDisplacement`、
`cellDisplacement`、`points`、mesh velocity 和 mesh Co 均非零；rollback 后物理场
恢复，retry 再次驱动 ALE；一窗口资格 PASS。

这里使用的 `1e-4 m` transverse offset 是 diagnostic-only，不是 HH06 物理结果。

### 3.12 displacement semantics / feedback audit

**结论：** Structure 发送的是绝对 displacement，`D_expected-D_sent` 最大误差为
0，未发现增量累积或 double accumulation。晚期异常更符合：

```text
large fluid force
 -> large absolute structural displacement change
 -> mesh velocity / mesh Co increase
 -> flow velocity and omega growth
 -> further force growth
```

因此分类为 `FLUID_FORCE_FEEDBACK_RUNAWAY`，ALE 是放大路径；不能把它简化成
“位移语义累积错误”或单独的 ALE-only failure。由于已有 trace 只有 hash，没有完整
`q/qdot/qddot/M/K` 数值，独立结构能量闭合没有被伪造。

### 3.13 max-iterations=5：coupling iteration 仍不足且暴露 lineage defect

**问题：** 5 次隐式迭代后第一窗口 force residual 仍未达到收敛阈值；第二窗口
在 worker sequence 6 处 response header 缺失，导致后期 runaway 是否被迭代数解决
无法评价。

**根因：** worker 用 sequence 奇偶判断 same-window retry / next-window first request。
当窗口 1 在 sequence 5 提交后，sequence 6 被错误当成同窗口请求。

### 3.14 worker lineage transition 修复

**修复范围：** 仅隔离版 C++ worker state machine；没有改 Fluid adapter、OpenFOAM
case、preCICE XML、SHM1 或物理参数。

**新判定：**

- same-window retry：`global_step/bridge_step/integer_tick/time_s/dt_s` 全部保持同一；
- next-window first request：step/bridge/tick/time 按一个 dt 严格前进，dt 不变；
- sequence/request/transaction ID 继续单调递增，duplicate guard 保留；
- 不再使用 sequence 奇偶作为窗口判据。

**隔离验证：**

| physical window | requests | rollback | response headers | result |
|---:|---|---:|---:|---|
| 1 | sequence 1–5 | 4 | 5/5 | PASS |
| 2 | sequence 6–10 | 4 | 5/5 | PASS |

结果为 `PASS_HH06_WORKER_LINEAGE_TRANSITION_FIX_AUDIT`，但 qualified binary 没有
部署到 `slice0000`，也没有自动进入真实 FSI。

## 4. 当前状态矩阵

| 链路层 | 状态 | 说明 |
|---|---|---|
| HH06 contract / P1 q0 | PASS | 198 DOF、静态平衡、单点映射 |
| SHM1 Python/C++ protocol | PASS | qualified worker 已证明 |
| physical checkpoint rollback | PASS | q/qdot/qddot 精确恢复 |
| transport ID rollback语义 | PASS | retry 使用新 IDs，保持单调 |
| preCICE initial data | PASS | initialize 前写 absolute Displacement |
| one-window handshake | PASS | Fluid/Structure mapping 正常 |
| checkpoint lifecycle | PASS | 同一窗口可多次 rollback |
| nonzero ALE one-window isolation | PASS | 仅诊断位移，不是生产物理 |
| 25-window ALE/FSI bounded qualification | **DO_NOT_PASS** | late-window runaway |
| production 50-window / 0.2 s FSI | 未授权/未完成 | 没有继续启动 |
| latest worker lineage fix deployment | 未部署 | 仅隔离 qualification |

## 5. 证据归档和边界

本目录 `evidence/` 归档了此前未进入 Git 的 27 个报告、结果 JSON 和 lineage
测试脚本。原始路径、报告中的 SHA256、运行边界和失败状态均保留。

未归档到公开仓库的内容：

- OpenFOAM 数值时间目录、网格副本、运行日志；
- worker/adapter 二进制及 build 目录；
- socket、core dump 和缓存；
- 仅用于一次性运行的临时大文件。

这些文件没有删除，仍在本地 runtime 目录中；本归档只上传可审查的文档、机器结果
和可复现诊断脚本。

## 6. 下一步授权边界

本归档完成后仍不授权：

- 自动部署 lineage 修复 worker；
- 启动 50-window；
- 启动 0.2 s production FSI；
- 修改 dt、松弛、SST、ALE 或物理参数。

需要人工审阅本归档后，单独决定是否进行 worker deployment、bounded retry 或新的
Fluid/ALE 诊断。
