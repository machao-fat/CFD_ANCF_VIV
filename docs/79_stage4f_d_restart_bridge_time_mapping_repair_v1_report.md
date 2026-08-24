# Stage 79 restart bridge time-mapping repair

## Gate

`STAGE4F_D_RESTART_BRIDGE_TIME_MAPPING_REPAIR_V1_GATE: pass`

本阶段仅执行离线代码修复和测试，未启动 MATLAB、OpenFOAM、WSL 或 CFD。

## 根因

Stage 75 的 step 559 -> 560 restart 同时使用了全局 step 和 case-local legacy bridge step。seed、target motion、scheduler 的 CFD 起始时间因此不一致，造成 `motion_ready` stale 和 `seed time must equal OpenFOAM start time`。这不是网络或 MATLAB license 结论。

## 修复

- `src/coupling/multi_slice_driver/real_process.py` 允许显式传入 case-local target bridge step。
- `src/coupling/multi_slice_real_campaign/campaign.py` 将 `current_clock_step` 作为 case-local 时钟，target 使用 `current_clock_step + 1`，提交后只递增一个局部步。
- 未修改 ANCF/EB 核心、正式 0.2.1 协议、物理参数或数值阈值。

canonical mapping 为：global 559 / 2.2075 s / 2207500000 -> global 560 / 2.20875 s / 2208750000，legacy bridge seed 0 -> target 1。

## 验证

- compileall：通过。
- restart bridge 专项：13 passed，0 failure。
- 根目录 unittest：935 collected，934 passed，0 failure，1 skipped，`OK`。
- 旧 Stage 1--78 证据和失败 runtime 只读保护，未复用。
- 真实进程启动数：MATLAB=0、OpenFOAM=0、WSL=0、CFD=0。

## 状态与下一步

Stage 75 本次未启动；attempt2--6 仍不可复用。修复 Gate 通过后，具备重新申请资格，但必须获得新的明确授权，并创建全新 `run_id`、`case_id`、runtime 和 results。正式统计仍保持 `frequency=not_evaluable_insufficient_cycles`、`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。不得自动启动下一段或其他研究 campaign。
