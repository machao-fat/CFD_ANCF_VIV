# HH06 REAL IMPLICIT MESH ROLLBACK OBSERVABILITY AUDIT

## 结论

最终状态：`DO_NOT_PASS_ALE_MOTION_NOT_EXERCISED`

本轮确实使用了真实 `Fluid_0000`、真实 `Structure_0000`、SHM1 qualified worker 和
parallel-implicit preCICE，并在一个 0.0002 s coupling window 内触发了至少一次
checkpoint rollback。可观测的物理字段和几何字段在 rollback 后精确恢复；但本窗口从
静态 `q0` 开始，实际 ALE 网格没有发生非零位移，且 checkpoint-write 时 `meshPhi`
尚未以可查对象名注册。因此本报告不宣称“生产 ALE 非零运动 rollback 已通过”。

## 执行边界

- 原始算例：`\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000`
- 隔离算例：`D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\hh06_real_mesh_rollback_audit_v1\case`
- 只执行 1 个隔离 coupling window，`dt=0.0002 s`，`max-time=0.0002 s`，`min/max-iterations=2`
- 未调用原始 `launch.sh`
- 未启动 50-window、长时间 FSI、multi-slice 或任何 fake participant
- 原始 `slice0000` 仍只有原有 `30` 时间目录；未产生新的原始时间目录
- 隔离 XML 仅改变 exchange-directory、max-time 和 max-iterations；流体网格、RAS、fvSchemes、fvSolution、物性和 SHM1 合同未改

## 身份与 provenance

### Structure_0000

- 入口：`D:\研二文件\开题准备\CFD_ANCF_VIV\tools\hh06_single_slice_structure_0000_participant_v1\structure_0000_participant.py`
- 真实执行参数：`--case <isolated-case> --run --worker <qualified-worker> --max-windows 1`
- contract audit：`PASS`
- P1 q0：198 DOF，REF_NE32，静态平衡，速度为零
- 单点接口：`s=2.97 m`，单个 Structure mesh coupling point
- 结构最终记录的单步 motion：`[1.0452091616563741e-07, 9.588691723237472e-08, 4.163871573314992e-04]`

### qualified worker

- 路径：`\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000\cfd_ancf_ancf_kernel_worker_shm1_qualified`
- SHA256：`69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF`

### Fluid adapter

本轮使用隔离诊断库，未覆盖生产库：

- diagnostic library：`/home/machao/OpenFOAM/hh06_real_mesh_rollback_audit_v1/diagnostic_lib/libpreciceAdapterFunctionObject.so`
- SHA256：`10dc208671840f3e8b800a10ccbad0cb703acf86185ab9c7aa15704b5fcf0ec4`
- build ABI：同一 `/opt/openfoam10` OF10、v1.3.0-compatible source baseline
- 诊断库只增加 JSONL 指纹读取，不改变流体求解逻辑
- production adapter library 未被覆盖

## preCICE/solver 证据

Fluid 日志显示：

1. `Fluid_0000` 与 `Structure_0000` 建立 primary/secondary communication；
2. 一阶 implicit trial 完成后 Force 收敛判据未通过；
3. preCICE 进入第二 iteration；
4. `CHECKPOINT_READ_AFTER_RESTORE` 指纹事件出现；
5. 第二 iteration 完成后 time window accepted，preCICE 在 `t=0.0002` 结束。

过程没有 `NaN`、`Inf`、FPE、duplicate-ID、checkpoint error 或 preCICE convergence failure。

## fingerprint 事件

`fluid_rollback_fingerprint.jsonl` 事件顺序为：

| event | window | iteration | physical time |
|---|---:|---:|---:|
| CHECKPOINT_WRITE | 1 | 0 | 30.000000 s |
| PRE_ROLLBACK_TRIAL | 1 | 1 | 30.000200 s |
| CHECKPOINT_READ_AFTER_RESTORE | 1 | 1 | 30.000000 s |
| AFTER_INPUT_UPDATE | 1 | 1 | 30.000000 s |
| AFTER_INPUT_UPDATE | 1 | 1 | 30.000200 s |

这证明本轮确实触发了真实 rollback/read，而不是固定网格或人工 participant。

## A. rollback 状态一致性

以下为 checkpoint-write 与 rollback-read 的 FNV1a64 canonical hash 对照：

| state | write | read | 结果 |
|---|---|---|---|
| points | `84b09858d2e5c718` | `84b09858d2e5c718` | PASS |
| oldPoints | `84b09858d2e5c718` | `84b09858d2e5c718` | PASS |
| phi | `5e737856cbb4000a` | `5e737856cbb4000a` | PASS |
| cellVolume | `e49d59bd4291f4bd` | `e49d59bd4291f4bd` | PASS |
| faceArea | `a8d92acd46eb7fe9` | `a8d92acd46eb7fe9` | PASS |
| U | `61e10298d5371efa` | `61e10298d5371efa` | PASS |
| p | `ab1feb7ccf1379cf` | `ab1feb7ccf1379cf` | PASS |
| k | `a1bd220b765c52dd` | `a1bd220b765c52dd` | PASS |
| omega | `6b21c90b8ea937f2` | `6b21c90b8ea937f2` | PASS |
| nut | `32af9d4eac163202` | `32af9d4eac163202` | PASS |
| pointDisplacement | `403a37f08d8872c4` | `403a37f08d8872c4` | PASS |
| cellDisplacement | `054f811aba347c5a` | `054f811aba347c5a` | PASS |
| meshPhi | not registered at write | `643e6457c48e9183` | NOT OBSERVABLE |

结论：除 `meshPhi` 写入侧观测缺口外，几何、速度、压力、湍流状态和 ALE 辅助场均
精确恢复。`meshPhi` 的缺口是诊断可见性问题，不能被解释成 hash 不一致，也不能被
解释成 hash 一致。

## B. rollback 后 mesh velocity 是否突变

本窗口所有可观测 mesh-motion 量均为：

- max point displacement：`0 m`
- max mesh velocity：`0 m/s`
- mesh Courant：`0`
- `cellDisplacement` max：`0 m`
- `pointDisplacement` max：`0 m`

因此没有观察到 rollback 后 mesh velocity jump；但这同时说明本窗口没有实际施加
非零 ALE 运动，不能替代非零运动审计。

## C. Co 爆炸前是否已经有 mesh motion 异常

Fluid 日志中两次 trial 的 Courant 数均为：

`mean=0.01601199855, max=0.4182184878`

没有 Co 爆炸、没有 mesh-motion anomaly、没有负体积证据。一次 trial 中：

- `k`：约 `2.70e-10 ... 1.59e-2`
- `omega`：约 `1.98 ... 9.38e4`
- 全部有限

所以本窗口不支持“rollback 后 ALE mesh motion 先异常、随后 Co 爆炸”的判断；本窗口
根本没有进入非零 ALE 位移场景。

## D. Structure displacement 与 Fluid received displacement

Structure_0000 使用真实 ANCF worker 计算 q0 和单步响应，最终记录的 x/y coupling
motion 为约 `1.0452e-7 m`、`9.5887e-8 m`。但是本窗口的 initial displacement 是
静态 q0 对应的零位移，Fluid 的 `pointDisplacement` / `cellDisplacement` 指纹在
checkpoint、rollback 和第二 trial 中保持不变，最大值均为 0。

因此已证明真实 Structure_0000 路径存在并推进了一个 ANCF step，但没有足够的实际
非零位移窗口来证明 ALE 网格在 rollback 前后使用了相同的非零结构输入。该项标记为
`NOT_EXERCISED_NONZERO_ALE_INPUT`。

## 最终判定

| 项目 | 判定 |
|---|---|
| 真实 Fluid/Structure/preCICE 路径 | PASS |
| 至少一次真实 checkpoint rollback | PASS |
| 物理场与几何字段 rollback 恢复 | PASS（meshPhi 写入 hash 除外） |
| rollback 后 mesh velocity jump | 未观察到 |
| Co 爆炸前 mesh motion 异常 | 未观察到 |
| 非零 ALE mesh rollback 一致性 | NOT EXERCISED |
| 本轮完整生产 ALE observability audit | **DO_NOT_PASS_ALE_MOTION_NOT_EXERCISED** |

本轮没有自动重试、没有续算、没有修改原始算例。若要完成“非零 ALE mesh rollback”资格，
下一轮需要人工单独授权至少一个已提交非零 displacement 的后续窗口，并同时修复诊断版
`meshPhi` 在 checkpoint-write 时的对象查找；本报告不自动启动该后续实验。

## 证据文件

- `fluid_rollback_fingerprint.jsonl`
- `fluid.stdout` / `fluid.stderr`
- `participant.stdout` / `participant.stderr`
- `case/precice-config.xml`
- `adapter_build.log`

SHA256 已记录在同目录的 `HH06_REAL_MESH_ROLLBACK_AUDIT_RESULT.json`。
