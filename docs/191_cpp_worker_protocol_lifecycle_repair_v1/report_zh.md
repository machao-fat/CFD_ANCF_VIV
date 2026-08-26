# Stage191 C++ worker protocol/lifecycle repair

本阶段修复了上轮代码审查发现的四个问题：生产路径现在必须由 `CppConfirmRun` 内部调用 `build_predictor_motion_by_slice()`，并在任何 barrier/backend 触碰前完成 `MotionRecord` schema、step、time、case 和 slice 校验；worker stop 会审计并报告非零退出码；有界 reader thread 会被保存、收口并计入 residual；裸 transport client 明确不拥有 OS 进程，进程返回码由 supervisor 审计。

验证：专项 30 passed；根目录 1200 passed, 2 skipped；compileall、CMake/MSVC Release 和 3 个 C++ selftest 全部通过。真实 MATLAB/OpenFOAM/WSL/CFD 启动数为 0/0/0/0，owned residual=0。未修改 ANCF/EB 核心、物理参数、global dt、slice 数、数值阈值、正式协议或 Stage1–190 旧证据。

Gate：`STAGE4F_D_CPP_WORKER_PROTOCOL_LIFECYCLE_REPAIR_V1_GATE: pass`

正式状态继续保持：`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。本阶段没有启动 CFD；后续真实计算仍需新的明确授权。
