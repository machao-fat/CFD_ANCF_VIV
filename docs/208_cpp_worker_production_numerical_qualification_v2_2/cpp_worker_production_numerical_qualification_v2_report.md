# C++ 生产数值核心资格验证 V2.2

Gate：`STAGE4F_D_CPP_WORKER_PRODUCTION_NUMERICAL_QUALIFICATION_V2_2_GATE: pass`

本阶段以 accepted source step 559、time `2.2075 s` 为共同初值，MATLAB 与 C++ 均在相同生产数值合同下连续计算 step `560--599`。合同固定为 `dt=0.00125 s`、Gauss=`3`、`max_newton=40`、质量积分 Gauss=`5`、正式协议 `0.2.1`。初始 `q/qdot/qddot`、base load、三个 slice force 与 102x102 质量矩阵相同。

40/40 步均通过身份、有限值、return code、Newton iteration 和逐字段比较。全窗口最大绝对差为：`q=7.63e-16`、`qdot=8.88e-14`、`qddot=7.11e-11`、internal force=`2.76e-08 N`、external/generalized force=`0`、residual=`2.91e-10`。这些值均在资格比较容差内。

已 pin 的 C++ worker SHA-256：`c3e6bb50d4dd6de74a6aa080ed37b8aa0a8d2385c41321a38e3e5521aa319170`。MATLAB golden 同时保留了 R2021b 原始 payload hash 和从 JSONL 数值重新计算的 canonical hash；前者存在 R2021b Java/JSON 字节兼容性差异，后者可由独立审计方复算，且没有改动任何数值、身份或输入。

真实启动计数：MATLAB=`1`、C++ worker=`1`、OpenFOAM=`0`、WSL=`0`、CFD=`0`；两个 owned 进程均正常关闭，residual=`0`。Stage 75、E5-C、五/九 slice、长时 VIV、锁定区和实验验证均未启动。历史 Stage 1--205 证据、accepted source 和旧 runtime 均为只读。

结论：当前已 pin 的生产 C++ 数值核心可标记为 `validated`。此结论不自动授权任何物理 CFD；后续真实 segment 仍需新的明确授权，并且只可在 worker 二进制、数值合同、模型/协议身份和核心代码均未改变时引用本资格结果。任一变化均须重新进行 MATLAB/C++ dual-run。
