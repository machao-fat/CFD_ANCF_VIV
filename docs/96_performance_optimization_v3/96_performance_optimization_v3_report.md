# Stage 96 V3 增量性能优化最终报告

## Gate

`STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V3_GATE: pass`

最终候选为全新 `stage96_v3_true_start_overlap_20260823`，runtime 为 `runtime/performance_optimization_v3/confirm_025`。固定范围为 40 steps、0.05 s、三 slice，source 为 global step 559、time 2.2075 s、tick 2207500000；source checkpoint SHA-256 为 `341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`。

## 真实性能结果

confirm025 wall clock 为 `35.4478716 s`，完成 `40/40` physical committed 和 `40/40` fully audited，step 范围 `560–599`，case-local bridge step `1–40`，tick `2208750000–2257500000`，连续性通过。

相对已通过的 V2 M+O+P 参考 `42.8945183 s`：

- 绝对减少：`7.4466467 s`
- 相对减少：`17.3603691%`
- 目标：`<=36.5 s`，通过

最终阶段统计：总 step 平均 `0.736886 s`、P50 `0.726259 s`、P95 `0.836188 s`；MATLAB 平均 `0.082808 s`；OpenFOAM 平均 `0.941178 s`；IPC 平均 `0.072745 s`；WSL 平均 `0.030503 s`。首步 WSL 启动峰值已从此前约 7–10 s 级别移出 step 计时，prewarm 后首步 WSL phase 为 `0.019336 s`。

## 已实现优化

1. MATLAB worker 每 segment 启动一次并保持内存态 state。
2. 每个 OpenFOAM slice 每 segment 启动一个常驻进程。
3. 三 slice 并行执行，仍由 global barrier 统一收集 motion、CFD、force/load 和 checkpoint。
4. OpenFOAM source-time seed prewarm 与 MATLAB initialize 真正并行；target-time motion 仍在 scheduler barrier 后发布。
5. segment 级复用并行 slice executor，关闭时显式收口。
6. checkpoint hash cache、forceCoeffs 诊断输出抑制、compact force snapshot、ASCII precision 15、direct WSL 和 exchange fast atomic write 均为显式合同选项。
7. 只读资源审计改为不跟随链接的 `os.scandir` 遍历，字节数保持一致。

persistent IPC 没有实现，仍标记为 `persistent_ipc=false`，未计入收益；没有通过改标签或减少审计来宣称 IPC 优化。

## 物理与安全审计

- MATLAB：1 次启动、return code 0、正常关闭。
- OpenFOAM/WSL：3 个 slice 各 1 次启动、return code 0、日志均有最终 `End`。
- owned residual：`0`。
- 最大 CFL：`0.0585840683`；最大 `|Cd|`：`1.6095226259`。
- 最大 geometry error：`4.163336342344337e-16 m`。
- 最大 virtual-work relative error：`5.888935289778614e-16`。
- 最大 velocity consistency：`3.4124903136243576e-06`；force conversion error：`0`。
- 未创建 step 600、额外 block、额外 slice 或额外时间窗。

ANCF/EB 核心、物理参数、global dt、slice 数、稳定化参数、数值阈值、统计门槛和正式 0.2.1 协议语义均未修改。Stage 1–95 旧证据、Stage 74 source、attempt7–19 runtime 均只读保留。主线 Stage75、E5-B、E5-C、五/九 slice、长时 VIV、锁定区和实验验证均未启动。

## 测试

- compileall：通过。
- V3 专项：`28 passed`。
- V2 相关回归：`33 passed`。
- Stage67–94 选定合同/runner 回归：`4 passed`。
- 根目录 unittest：`1026 collected, 1025 passed, 0 failure, 0 error, 1 skipped`，最终 `OK`。
- 离线测试真实进程启动数：MATLAB=0、OpenFOAM=0、WSL=0、CFD=0。

confirm019–025 均使用独立 run/case/runtime；失败或未达目标的 confirm 证据没有重试或复用。最终 confirm pair 差异低于 10%，不需要第三次最终 confirm。

## 下一步资格

优化 Gate 已通过，因此具备在新的明确授权下申请一个全新 run_id、case_id、runtime 的真实 CFD segment 的性能资格；本阶段没有自动启动任何主线计算。正式状态继续保持：`frequency=not_evaluable_*`、`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。
