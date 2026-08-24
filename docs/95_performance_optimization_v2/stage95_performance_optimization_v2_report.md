# Stage95 性能优化 V2 当前报告

## 当前结论

`STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: do_not_pass`

本阶段的离线合同、telemetry 校验、消融矩阵和归因代码已完成并通过专项测试；真实 40-step benchmark 尚未执行，因此不能宣称效率提升，也不能从 Stage75 attempt19 或 Stage90 mock 推断真实 speedup。

## 已完成

- 新增隔离包 `src/coupling/performance_optimization_v2`。
- 固定 source step 559、time 2.2075 s、tick 2207500000、40 steps、0.05 s、三 slice 的合同校验。
- 校验 global step、case-local bridge step、time、tick、request/transaction identity、phase timing、return code、owned residual 和连续性。
- 支持 B/M/O/P/I/A 组合矩阵、leave-one-out marginal、归一化权重和 pair interaction 计算。
- MATLAB worker adapter 已支持显式 `run_id/case_id/source_global_step`，不再把 global step 直接当作 case-local bridge step。
- transport 默认把 worker loop 所在目录加入 MATLAB path；Codex 仍不启动 MATLAB。
- 新增 v2 `PersistentSliceCoordinator`、`OpenFOAMProcessEngine`、mapped IPC 和批量 audit writer；每个 slice 只允许一次 start，source step 559 到 target step 560 映射为 case-local bridge step 1，三 slice commit 受全局 barrier 保护。

## 验证

- `compileall`：通过。
- Stage95 专项：8 passed。
- MATLAB worker bridge：4 passed。
- user-session worker：2 passed。
- 根目录 unittest：973 collected，0 failure，0 error，1 skipped，`OK`。
- 本阶段真实 MATLAB/OpenFOAM/WSL/CFD 启动数：0。
- owned residual：0；全量回归产生的两个明确 fake process-tree 测试残留已按 PID 精确清理。

## 未完成与边界

尚缺用户交互 SessionId=1 runner 产生的独立真实 B/M/O/P/I/A/组合测量，以及把现有真实 campaign 接入新 coordinator 的 bounded harness。没有这些证据，就不能输出真实 phase reduction、P50/P95、重复性、speedup 或最终权重，也不能申请后续主线 CFD。当前仍禁止 E5-B、E5-C、五/九 slice、长时 VIV、锁定区和实验验证。

物理核心、数值阈值、global dt、slice 数、正式 0.2.1 语义和 Stage1-94 旧证据均未修改。

统计状态继续为：`frequency=not_evaluable_*`、`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。
