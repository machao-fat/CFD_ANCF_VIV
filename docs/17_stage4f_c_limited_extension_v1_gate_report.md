# Stage 4F-C 三切片受限延长瞬态 Gate 报告

## Gate 结论

`STAGE4F_C_LIMITED_EXTENSION_V1_GATE: pass`

唯一终态为 `success_twenty_step_limited_transient_and_midpoint_restart`。从已接受 step 9 checkpoint 连续完成 step 10–19，并仅在 continuous 10/10 通过后，从 step 14 checkpoint 在 fresh case 中重跑 step 15–19。由此形成从原始起点计算的 20 个连续物理步，总窗口 0.0125 s。

## 数值结果

- continuous block 1：step 10–14，5/5 committed。
- continuous block 2：step 15–19，5/5 committed。
- midpoint restart：step 15–19，5/5 committed。
- 新连续分支最大 CFL：0.03394465303764074。
- 新连续分支提交态最大绝对 Cd：1.0589425212797177。
- 最大虚功相对误差：2.1792977944496147e-16。
- 最大力转换相对误差：0。
- 最大位置差/D：8.701459108589557e-11。
- 最大速度差/U：2.7844663946170987e-7。

## Restart 与证据链

midpoint restart 的五个 checkpoint 与 continuous 后半段逐步一致：q/qdot/qddot 和 previous slice forces 最大相对误差均为 0；每步 24 项 CFD manifest 场哈希一致，共 120 项。

由于正式 0.2.1 checkpoint 不内嵌父 checkpoint 哈希，本阶段额外从磁盘重建外部 lineage：continuous 10 条、restart 5 条。每条记录绑定父子 checkpoint 路径和 SHA-256、合同 SHA-256、24 项 CFD 场聚合哈希、previous forces 哈希及 ANCF runner checkpoint 哈希。跨块父子 SHA 链通过。

父 checkpoint SHA-256 前后均为 `c27916359016ffbd09fef9d6eed19175a48dc85a1a11ee00f12664d240023fb0`。

## 测试与进程

- `python -m compileall -q src tests`：通过。
- 新阶段专项：11/11 通过。
- 根目录无过滤 unittest：799/799 通过。
- owned process：305 启动、305 关闭、0 残留；非零返回码 0。
- 重型 candidate engine 最大并发保持为 1。
- runtime、TEMP/TMP/TMPDIR、Python cache 和 MATLAB PREFDIR 均位于 D 盘独立目录。

## 研究边界

`THREE_SLICE_TWENTY_STEP_LIMITED_TRANSIENT_NUMERICAL_STATUS: accepted`

该窗口仅约 0.0023 个结构一阶周期，不能称为涡脱落统计、VIV 响应、锁定区或物理验证。进一步三切片延长必须重新授权；五/九切片和长时 VIV 仍不得进入。
