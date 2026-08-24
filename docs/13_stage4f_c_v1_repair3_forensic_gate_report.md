# Stage 4F-C-v1-repair3 法证审计与 Gate 报告

## 唯一终态

`failure_terminal_pre_execution_genuine_frozen_numerical_gate_failure`

`STAGE4F_C_V1_REPAIR3_GATE_RECOMMENDATION: do_not_pass`

repair3 未启动 MATLAB、WSL/OpenFOAM 或真实 A/B/C。原因是 Phase 1 对 repair2 原始数据的独立复算已满足 Phase 2 的硬停止条件；继续重跑会违反冻结合同。

## 首个失败定位

repair2 Branch A 的 `step=2` 是第三个全局步，目标时刻为 `1.515 s`。slice 0 的原始流向力为 `5438.782283622542 N`，按冻结 `q_inf=500 Pa`、`D=1 m`、`Aref=1 m2` 得 `Cd=10.877564567245084`，首先超过 `abs_Cd_max=10`。slice 2 为 `5501.555433557628 N`，得 `Cd=11.003110867115256`。两者都由 OpenFOAM `forceCoeffs` 独立复现。

raw force 先按 `unit_span_m=1 m` 转为单位跨度力，再仅乘一次 `slice_length_m=16.666666666666668 m`。转换误差为 0。未发现总切片力再次乘 span、使用 `D^2`、混用 extrusion thickness、旧力复用、重复消费、缺片或时间错位。因此根因分类为 `genuine_frozen_numerical_gate_failure`，而非 `force_scaling_or_aggregation_defect`。

同一步最大 predictor/committed 速度差为 `0.01873367971574207 U`，超过冻结上限 `0.01 U`。正式 H 插值、六自由度节点布局、时间层与 step 标签均能复现该值；CFD mesh 与已发布 predictor motion 的误差约为机器精度。该速度差不是节点排列或归一化造成的假阳性，但即使重新解释此项，独立的原始 Cd 超限仍足以阻止重跑。

## 身份与进程证据

原始父 checkpoint SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`。32 个父保护文件的组合 SHA-256 在审计前后均为 `9e51091ce3b62dc379769db6ff8ea0a7afe47950bb60b92615b2990ea9e2ee01`。

repair2 三个 committed checkpoint 的时间依次为 `1.51/1.5125/1.515 s`，每步三片完整且只有一个 unified commit。父 checkpoint JSON、父 ANCF MAT 和 `fixed_point_state.mat` 是三个不同序列化对象，已分别记录 lineage，未混称。

repair2 的 15 个 owned process 均已关闭且残留为 0；但 9 条 OpenFOAM WSL launcher 记录缺少 `creation_time`、`parent_pid`、`command_line`、`cwd` 和日志等字段。repair3 离线工具已将这些字段设为强制项。该缺陷属于次要 `runtime_evidence_orchestration_defect`，不改变数值失败结论。repair3 本身启动/关闭/残留为 `0/0/0`。

## 测试与边界

`compileall` 通过。repair3 专项 `24/24`、原 Stage 4F-C 专项 `26/26`、classifier repair 专项 `37/37`、repair2 专项 `38/38` 均通过。全仓 `-f` 实际收集 `698` 项，`698/698` 通过，0 failure、0 error。

A/B/C 请求步数为 `20/20/40`，repair3 实际步数为 `0/0/0`；restart 与 dt/2 均未运行。下一授权点只能是用户明确修改冻结的物理/数值研究合同（例如 Cd 门槛、初始瞬态处理、域/网格/边界或研究范围）后创建新阶段；本任务不得自行选择或修改其中任何一项。

本报告不构成涡脱落统计、稳定 VIV 响应、锁定区、实验验证或 Stage 4E 物理验证。
