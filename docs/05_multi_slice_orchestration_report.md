# 阶段四B：多切片调度、原子 checkpoint 与 OpenFOAM 模板报告

## STATUS

`partially_completed`

Mock 调度、失败停止、原子 checkpoint、restart、模板和既有回归均完成。两个真实 OpenFOAM 10 独立切片的短时规定运动/握手已运行成功，但真实时间目录缺少必需的 `motionScale`，因此真实烟测的 checkpoint 子项按 fail-closed 规则标记 blocked；没有伪造该文件。

## 范围和边界

本任务只实现了冻结的 Stage4-Multislice Draft 1 编排层：多切片状态机、全切片时间屏障、ready/consumed 事务、失败停止、原子全局 checkpoint、严格 restart、mock 进程和参数化 OpenFOAM 模板。

没有修改 ANCF/EB 核心、现有 persistent runner、生产版 `ancfFileMotion`、阶段三 case、在线公共协议或 `multi_slice_mapping`。没有进行正式双切片 CFD–ANCF 自由耦合集成，也没有作整根柔性立管 VIV 验证声明。

## 状态机

```text
INITIALIZED
  -> PREDICTED
  -> MOTION_PUBLISHED
  -> MOTION_CONSUMED
  -> CFD_ADVANCED
  -> LOADS_READY
  -> LOADS_CONSUMED
  -> STRUCTURE_CORRECTED
  -> CHECKPOINT_PREPARED
  -> COMMITTED

任何阶段发生错误 -> FAILED（终止本事务；不允许继续下一步）
```

非法跳转被 `MultiSliceScheduler` 拒绝。每个事务写入 JSONL 事务日志，包含 `case_id`、`step`、`time_s`、`slice_id`、事件、UTC 时间、payload hash 和状态。

## 时间屏障和事务顺序

调度器严格执行：

1. 从最后一个 committed 结构状态调用 `predict_all`，一次性返回全部切片运动。
2. 按 `slice_id` 校验完整集合、坐标恒等式、有限性、step/time/iteration 和静态身份。
3. 为每个切片写不可变运动 CSV；payload 完整写入、flush、fsync、atomic replace 后才写 ready。
4. 等待全部 motion consumed；任何一个切片缺失、超时或标识不一致都失败停止。
5. 仅在全切片 consumed 后调用每个 CFD slice 的 `advance_one_step`。
6. 等待全部 load ready，重新读取和验证所有 load payload；不使用旧载荷 fallback。
7. 所有 load 通过后才发布 load consumed，并按 `slice_id` 升序形成积分力集合。
8. 只把 `force_x_N`、`force_y_N`、`force_z_N` 送入 `correct_all`；调度器不再乘 `slice_length_m`。
9. 结构校正先产生 staged state；checkpoint manifest 提交成功后才调用 `commit_corrected`。
10. 只有 `status=committed` 的全局 manifest 存在后才进入下一步。

## 文件布局和 marker

实现使用：

```text
exchange/
  config.json
  slice_manifest.json
  transaction_log.jsonl
  slice_0000/
    motion/motion_stepXXXXXXXX_iterXXXX.csv
    load/load_stepXXXXXXXX_iterXXXX.csv
    motion/*.ready.json
    load/*.ready.json
    consumed/*.consumed.json
  slice_0001/ ...
```

运动和载荷都是 `0.2.0` 单行 UTF-8 CSV。ready marker 严格包含冻结字段、row_count=1、原始 payload SHA-256、config SHA-256 和 slice manifest SHA-256。consumed 只有在 ready、payload、hash、step/time/iteration 全部重新验证后发布，并带 `consumer`。marker 中的 digest 必须是 64 位小写十六进制 SHA-256。

力换算按冻结定义执行一次：

```text
force_2d = openfoam_force / unit_span_m
force_slice = force_2d * slice_length_m
```

`force_representation` 固定为 `integrated_slice_force_N`，局部基为固定全局基，因此 mock 中局部三分量与全局三分量逐项一致。

## 原子 checkpoint

第一阶段写入 `checkpoints/.pending/<checkpoint_id>/manifest.prepared.json`，并收集：

- 每个切片的 OpenFOAM 时间目录、`case_relative_path` 和文件 bytes/SHA-256；
- `U`、`p`、`phi`、`Uf`、`meshPhi`、`polyMesh/points`、`motionScale`、`uniform/time` 八个必需字段；
- ANCF 结构 checkpoint 及 `q`、`qdot`、`qddot`；
- 当前已提交切片积分力和 previous generalized force。

第二阶段重新校验所有文件和 hash，把状态改为 `committed`，以临时 JSON、flush、fsync、atomic replace 写入 `checkpoint_<id>.json`。pending/prepared/temp 文件永远不能用于 restart。任何字段缺失、文件内容变化、时间目录不一致或结构状态不完整都拒绝提交。

## restart 规则

restart 只接受 `status=committed` manifest，并重新计算所有 hash。实现拒绝：切片数量、slice_id、`s_ref_m`、`slice_length_m`、config hash、slice manifest hash、dt、ANCF checkpoint、q/qdot/qddot、任何 CFD 字段、文件内容、时间目录或 step/time 不一致。成功加载 step `n` 后返回 `next_step=n+1`，并将本次已提交切片力作为下一次 predict 的 previous force。

## 失败注入矩阵

| 类别 | 覆盖项 | 结果 |
|---|---|---:|
| 切片身份 | 缺失 slice、重复 slice_id | PASS |
| 运动屏障 | 缺 motion consumed、超时、错误 step/time/iteration | PASS |
| 载荷屏障 | 缺 load ready、旧载荷不可 fallback、进程非零退出 | PASS |
| 数值/哈希 | NaN、Inf、payload hash、config hash、slice manifest hash | PASS |
| checkpoint CFD | 缺 U/p/phi/Uf/meshPhi/polyMesh/points/motionScale/uniform/time | PASS |
| checkpoint ANCF | checkpoint 缺失、q/qdot/qddot 缺失 | PASS |
| 结构 | correct 失败 | PASS |
| 原子性 | pending/prepared/temp 不可 restart；未 commit 不推进 | PASS |
| restart | 切片数量、坐标、长度、配置 hash、文件篡改 | PASS |
| 连续性 | 成功 restart 后从下一 step 继续 | PASS |

所有 mock 失败场景均证明 `structure.committed_step` 不前进，且没有写出可用的 committed 全局 manifest。

## OpenFOAM 烟测

前置检查满足：mock 和模板通过、没有修改阶段三生产目录、OpenFOAM 10 可执行文件存在、同时进程数为 2。真实烟测运行两个独立二维切片，物理时间 `0 -> 0.0025 s`，每个进程推进 1 个时间步；运动通过阶段三已验证的 `ancfFileMotion` 物质化视图加载，并产生 motion consumed、force 文件和独立日志。

真实烟测结果：

- OpenFOAM：`OpenFOAM-10`；两个进程返回码 `[0, 0]`；最大 CFL `0.10381847`；无 SIGFPE/网格崩溃。
- 两个 case：`results/05_multi_slice_orchestration_tests/openfoam_smoke/case_slice_0000_retry3` 和 `case_slice_0001_retry3`。
- force 文件：各自 `postProcessing/cylinderForces/0/forces.dat`；ready/consumed 文件均产生。
- `0.0025` 时间目录写出 `U`、`p`、`phi`、`Uf`、`meshPhi`、`polyMesh/points`、`uniform/time`，但没有 `motionScale`。
- 因此真实 smoke summary 为 `blocked_checkpoint_fields`；没有把初始 `0/motionScale` 复制到后续时间目录，未伪造 checkpoint 完整性。

## 未解决接口问题和请求 Sol 处理

详见 [05_online_protocol_patch_request_from_orchestrator.md](05_online_protocol_patch_request_from_orchestrator.md)。核心请求是：

1. 决定 `0.2.0` 不可变 payload 到现有 `ancfFileMotion` `0.1.0` materialized view 的正式桥接位置。
2. 为生产 ANCF runner 明确 staged `correct_all`、late commit、discard/rollback 语义。
3. 明确 OpenFOAM 生产 checkpoint 如何在每个时间目录写出和 hash `motionScale`。
4. 由 Sol 创建并冻结正式 `docs/05_multi_slice_contract.md`，复核本实现的字段顺序和相对路径语义。

## 结果和建议

机器可读结果位于 `results/05_multi_slice_orchestration_tests/orchestration_test_summary.json`：mock 两切片和五切片成功，29 个故障注入子场景通过，14 个 checkpoint 场景通过，9 个 restart 场景通过，结构失败推进标志为 false。阶段四正式双切片 CFD–ANCF 集成尚未开始。

本任务对 Gate 4A 的建议为：**建议通过**，前提是 Sol 复核上述 staged structure 接口和真实 OpenFOAM `motionScale` checkpoint 请求；这不是对 Gate 4A、Gate 4B、阶段四或整根立管 VIV 的自行宣布。

