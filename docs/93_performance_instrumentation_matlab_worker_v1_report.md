# Stage93 性能埋点与 MATLAB 常驻 worker 离线报告

## 结论

`STAGE4F_D_PERFORMANCE_INSTRUMENTATION_MATLAB_WORKER_V1_GATE: pass`

本阶段严格离线完成。没有启动 MATLAB、OpenFOAM、WSL 或 CFD。Stage1--92 证据、Stage66 partial、Stage68/69 探针、attempt7--19 runtime 和物理 source 均保持只读。

## 实现

新增隔离包 `src/coupling/performance_instrumentation_matlab_worker_v1`，包含：

- canonical JSON、SHA-256 和 UTF-8 worker request/response 协议；
- 一个 segment 一个 worker 的生命周期模型；
- 每个 segment 先执行 1 次 initialize，再执行 40 次 prediction/correction 请求；
- global step、case-local bridge step、time、tick、request/transaction identity 校验；
- output hash、size、mtime_ns、return code、finite audit、PID 和 command line 审计；
- stale、duplicate、out-of-order、5001、非零返回、超时、断连、NaN/Inf、缺失输出和身份错配 fail-closed；
- 旁路 `StepTrace` 性能记录器，输出每个 phase 的 start/end、step total、P50/P95/max 和资源/残留字段；
- owned child/grandchild 精确清理与非 owned 保护模型。

## 性能证据边界

`performance_baseline.json` 是离线协议验证，不是真实 CFD 计时。它证明 40 个请求由一个 worker 完成且 `worker_start_count=1`、真实外部启动数为零。最近真实 attempt19 的 `911.968 s` 只作为历史参考，不被离线毫秒计时替代。

现有真实路径仍存在每步 MATLAB/OpenFOAM/WSL 启动，因此本阶段尚未宣称真实加速；真实 worker 接入必须经过后续独立授权和新 runtime 测量。

## 合同保护

未修改 ANCF/EB 核心、物理参数、global dt、slice 数量、稳定化参数、数值阈值、统计门槛或正式 0.2.1 协议语义。没有启动 Stage75、E5-C、五/九 slice、长时 VIV、锁定区或实验验证。

## 统计状态

- `frequency=not_evaluable_performance_optimization_only`
- `FORMAL_STROUHAL_STATUS=not_completed`
- `STABLE_VIV_RESPONSE_CLAIM=not_completed`
- `LOCK_IN_CLAIM=not_completed`

只有本 Gate 通过并取得新的明确授权后，才可申请全新真实 segment；本阶段不自动启动任何 CFD。

## 测试

- compileall：通过；
- Stage93 专项：8 passed，0 failure，0 error；
- Stage90 性能离线回归：16 passed，0 failure，0 error；
- 根目录 unittest：959 tests，0 failure，0 error，1 skipped，`OK`，193.347 s；
- 真实 MATLAB/OpenFOAM/WSL/CFD 启动数：均为 0；
- owned residual：0。
