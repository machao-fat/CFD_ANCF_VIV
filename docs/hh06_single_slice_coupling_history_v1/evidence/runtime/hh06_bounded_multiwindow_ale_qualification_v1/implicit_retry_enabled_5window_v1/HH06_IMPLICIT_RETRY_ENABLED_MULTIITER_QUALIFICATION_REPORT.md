# HH06_IMPLICIT_RETRY_ENABLED_MULTIITER_QUALIFICATION

## 结论

本次 5-window 隔离资格测试 **DO_NOT_PASS**。

- 按用户给定的 A/B/C 分类，当前结果属于 **B — `COUPLING_ITERATION_NOT_ENOUGH`**：第一物理窗口在 5 次隐式迭代后仍未达到 force convergence limit。
- 但“增加迭代是否消除后期 ALE/湍流 runaway”在本次运行中 **NOT_EVALUABLE**：第 1 个窗口提交后，第 2 个窗口在 worker sequence 6 处因协议 lineage 错误退出，未能跨过更长时间段。
- 本次没有足够证据支持 C `PHYSICAL_FLUID_STRUCTURE_INSTABILITY_REMAINS`。已完成的第 1 个窗口中，物理场保持有限，未出现 NaN、Inf、FPE 或负体积。

## 执行边界

本次仅使用隔离目录：

`D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\hh06_bounded_multiwindow_ale_qualification_v1\implicit_retry_enabled_5window_v1`

执行内容：

- `CFD_ANCF_ALLOW_IMPLICIT_RETRY=1`
- preCICE `min-iterations=2`、`max-iterations=5`
- `dt=0.0002 s`
- 目标最多 5 个 accepted windows
- 真实 `Fluid_0000`、`Structure_0000`、qualified SHM1 worker、parallel-implicit

未执行：

- 没有修改生产 case、物理参数、网格、fvSchemes、fvSolution、湍流模型或 worker/source；
- 没有启动 25-window 或 50-window；
- 没有自动 retry；
- 运行结束后无残留 `pimpleFoam`、Structure participant 或 worker 进程。

## 隔离配置与身份

| 项目 | 值 |
|---|---|
| OpenFOAM case | `...\\implicit_retry_enabled_5window_v1\\case` |
| OpenFOAM start time | `30 s` |
| coupling window | `0.0002 s` |
| max coupling windows | `5` |
| implicit retry environment | `CFD_ANCF_ALLOW_IMPLICIT_RETRY=1` |
| preCICE max iterations | `5` |
| preCICE min iterations | `2` |
| qualified worker | `/home/machao/OpenFOAM/coupling/singal_slice/slice0000/cfd_ancf_ancf_kernel_worker_shm1_qualified` |
| worker SHA256 | `69f045eb7f4576e5178d10711f0f265d7458282a7a4ecbcb860a913ada45beef` |
| adapter SHA256 | `8c2c0fda85dc7ed452eb144b03a92ac9bf739e62ee8369baf489b3439cfdf458` |

配置哈希和运行身份已保存在 `artifacts/run_identity.txt`；原始日志和 JSONL trace 未覆盖。

## 窗口结果

| window | time (s) | preCICE iterations | rollbacks | committed | force residuals (N) | displacement residuals (m) | max force norm (N) | max mesh velocity (m/s) | max mesh Co | max fluid Co | max omega |
|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|
| 1 | 30.0002 | 5 | 4 | yes | 0.0874, 0.0699, 0.0559, 0.0448, 0.0358 | 0, 0, 0, 0, 0 | 0.0874 | 2.55314e-4 | 8.27903e-4 | 0.418218 | 9.37928e4 |
| 2 | 30.0004 | aborted during retry lineage | not completed | no | 1.38e-3, 2.72e-2, 4.42e-2 observed on fluid side | no accepted structure response | n/a | n/a | n/a | 0.418102 | n/a |
| 3–5 | — | not reached | — | no | — | — | — | — | — | — | — |

第 1 窗口 force absolute convergence limit 为 `1e-3 N`，relative limit 为 `1e-5`。第 5 次迭代仍为 `0.0358 N`、relative `0.410`，所以 max-iterations=5 没有解决耦合收敛问题；该窗口是到达上限后提交，而不是 convergence PASS。

第 1 窗口的 ANCF worker 每次 Newton 迭代均为 3 次，残差约 `7.82694e-08`。rollback 后 q/qdot/qddot 哈希恢复到 checkpoint A，说明同窗口物理 rollback 本身在本次测试中保持一致。

## 失败位置与根因

participant stderr：

`HH06_STRUCTURE_0000_WRAPPER_ERROR: HH06ContractError: worker response header missing at sequence 6`

第 1 窗口使用 sequence 1–5，经过 4 次 rollback 后 sequence 5 提交。第 2 窗口的第一请求为：

```text
sequence=6
global_step=2
bridge_step=2
time=0.0004 s
dt=0.0002 s
request_id=910006
transaction_id=1910006
```

qualified worker 没有返回 response header，Structure participant 随后退出，Fluid 端出现 broken pipe。源码审计显示 `ancf_worker_main.cpp` 当前 lineage 判断仍含 sequence 奇偶假设：

- `lineage_mode == 2 && expected_sequence % 2 == 0` 时强制要求“同一个物理窗口”；
- 允许 implicit retry 的下一窗口分支只覆盖奇数 sequence；
- 因而 5 次迭代提交后，下一窗口 sequence=6 被错误当作同窗口请求。

这属于：

`WORKER_LINEAGE_WINDOW_TRANSITION_PARITY_DEFECT`

它是协议/worker lineage 问题，不是本次第 1 窗口观察到的流体湍流 runaway。该缺陷需要单独设计和审核，不能在本轮自动修复。

## 物理健康证据

第 1 个已完成窗口：

- `max fluid Co = 0.418218`
- `max mesh Co = 8.27903e-4`
- `max mesh velocity = 2.55314e-4 m/s`
- `max omega = 93792.8475`，保持有限；
- `min k = 2.70199e-10`；
- 最小 cell volume 仍为正，约 `7.687e-10 m3`；
- 未检测到 NaN、Inf、FPE、negative volume、OpenFOAM fatal 或 worker duplicate-ID。

第 2 窗口的 Fluid 侧在 participant 退出前仍显示有限 Co（约 `0.418102`），但没有完整结构响应，因此不能把它作为物理稳定性结论。

## 证据文件

- `participant.stdout`
- `participant.stderr`
- `fluid.stdout`
- `fluid.stderr`
- `structure_force_trace.jsonl`
- `fluid_rollback_fingerprint.jsonl`
- `read_path_trace.jsonl`
- `artifacts/run_identity.txt`
- `case/precice-config.xml`
- `case/system/controlDict`

## 最终判定

```text
classification = COUPLING_ITERATION_NOT_ENOUGH
qualification_status = DO_NOT_PASS
late_window_runaway_assessment = NOT_EVALUABLE
root_cause = WORKER_LINEAGE_WINDOW_TRANSITION_PARITY_DEFECT
```

下一步只能先审计/修复 worker 的物理窗口 lineage 判定；在人工批准前不进入 25-window 或 50-window，也不把本次结果写成物理 instability 结论。
