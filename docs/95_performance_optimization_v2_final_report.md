# Stage 95 最终综合性能优化报告

## 结论

最终候选采用 `M+O+P`：MATLAB worker 常驻、每个 OpenFOAM slice 常驻一个进程、三个 slice 并行并保留 global barrier。全新 confirm runtime 为 `MOP_004`，40 steps、0.05 s、三 slice，wall clock `42.8945183 s`。

最终 Gate：

`STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: pass`

## 真实对比

| 项目 | 结果 |
|---|---:|
| 新基线 B_002 | 965.1374652 s |
| 最终 MOP_004 | 42.8945183 s |
| speedup | 22.5003x |
| 最终 confirm steps | 40/40 |
| 物理窗口 | 0.05 s |
| slice | 3 |
| 最近两次 confirm | 45.9409463 / 42.8945183 s |
| 相对范围 | 6.86% |

## 启动与审计

- MATLAB segment 启动次数：1。
- OpenFOAM/WSL 每 slice 启动次数：1，共 3 个。
- 三 slice 每个 step 均完成 barrier 后再提交。
- global step：559 -> 560..599；case-local bridge step：1..40；time/tick 连续。
- MATLAB、OpenFOAM/WSL 返回码均为 0。
- MATLAB cleanup：closed；owned residual：0。
- 日志、checkpoint、raw snapshot、PID、命令行和过程审计均保留在新 runtime。
- 未声明未完成的 persistent IPC、audit batching 或其他附加因子。

## Phase timing

最终 trace 的每步总耗时平均 `0.9053 s`、P50 `0.7849 s`、P95 `0.9573 s`、最大 `5.2599 s`。稳态阶段主要耗时为 OpenFOAM 求解与同步；MATLAB 常驻后单步 MATLAB 平均 `0.0837 s`。首步 WSL 启动开销为一次性成本，未在每步重复产生。

## 保护审计

- ANCF/EB 核心、物理参数、global dt、slice 数量、稳定化参数、数值阈值和正式 0.2.1 语义未修改。
- Stage 1–94 旧证据、Stage 66 partial、Stage 68/69 探针、Stage 74 source、attempt7–19 runtime 均只读。
- Stage74 source SHA-256 仍为 `341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`。
- 未启动主线 CFD、E5-B/E5-C、五/九 slice、长时 VIV、锁定区、实验验证或正式统计。
- 5001 规则：只有明确 MATLAB/MathWorks/ApplicationService 上下文的 `5001` 才要求用户 runner；本次没有 5001。

## 验证

- compileall：通过。
- Stage95 专项：`33 passed`。
- 根目录 unittest：`998 collected, 997 passed, 0 failure, 0 error, 1 skipped`。
- 最终 Gate 证据：[final_direct_audit](../results/95_performance_optimization_v2/final_direct_audit/stage4f_d_solver_performance_optimization_v2_gate.json)。

正式频率、Strouhal、稳定 VIV、lock-in 和实验验证状态继续为未完成；本阶段仅证明性能优化收益。
