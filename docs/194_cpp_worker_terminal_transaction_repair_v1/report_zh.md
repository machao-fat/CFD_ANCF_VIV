# Stage194 C++ worker 终止性事务修复

本阶段纠正了上一轮把“物理 rollback”误设为确认 Gate 前提的设计问题。常驻 OpenFOAM 在消费 target-time motion 后已经推进；在同一 runtime 内回滚字段状态既不真实，也违背“不自动重试、不复用失败 runtime”的合同。

当前实现采用终止性事务：checkpoint 只在全部 commit callback 成功后公开；任何失败写入 `aborted` journal 和 `runtime_terminal_no_resume`；下次启动拒绝含未决 journal 的 runtime；real slice adapter 进入 terminal，清理但不声称能够回滚 CFD。该语义与既有 fail-closed 合同一致。

离线验证：C++ worker 专项 70 passed，phase timing 5 passed，compileall 通过。实际 MATLAB/OpenFOAM/WSL/CFD 启动数均为 0，owned residual 为 0。未修改 ANCF/EB 核心、物理参数、数值阈值、global dt、slice 数或正式 0.2.1 协议。严格 MATLAB/C++ 40-step 双算仍保持 validated。

Gate：`STAGE4F_D_CPP_WORKER_TERMINAL_TRANSACTION_REPAIR_V1_GATE: pass`

下一步必须等待新的明确授权，才能创建全新的有界 40-step、3-slice、0.05 s confirm；本阶段没有自动启动真实计算。
