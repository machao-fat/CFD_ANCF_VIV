# Stage 4F-D MATLAB correction step-528 forensic 报告

## Gate

`STAGE4F_D_E5_MATLAB_CORRECTION_FORENSIC_V1_GATE: pass`

本阶段纯离线完成，真实 MATLAB/OpenFOAM/WSL 启动数均为 0。Stage 66 失败现场未修改、未复用、未重试。

## 原始证据结论

- Stage 66 首个失败为 block 0、step 528 的 MATLAB `correct_00000528`，return code=1。
- step 527 correction return code=0；step 528 prediction return code=0；step 528 correction return code=1。
- 三个 OpenFOAM slice 在 step 528 均 return code=0 且日志包含 End。
- step 528 correction stdout/stderr 日志为空，`correction.mat` 输出不存在；因此 correction output freshness/identity 校验 fail-closed。
- 失败 JSON 明确记录 `MATLAB correct_00000528 failed with code 1`，没有 MATLAB 数值堆栈、license 错误或网络错误原文。

## GUI、worker 与网络

项目证据中没有 GUI login、batch worker license、`license('test','MATLAB')`、`license('inuse')`、ApplicationService、token refresh、DNS/TLS/HTTP 或代理事件的可验证记录。因此：

- GUI login 与 worker 授权：`insufficient_evidence`；不能互相替代。
- ApplicationService：`insufficient_evidence`。
- 网络错误：未被证明存在。
- 网络/授权是否解释 step 528：不能确认，不能归因。

## step 527/528 差异

已核对 run/case、step/tick/time、MATLAB command、输入 force、stabilizer、父 checkpoint 与输出状态。可确认差异为时间层推进、correction return code 由 0 变 1，以及 step 528 correction output 缺失。由于没有 step 528 correction output 和诊断 stderr，无法进一步区分授权、输入、数值或 orchestration 根因。

根因分类：`unknown_insufficient_evidence`，置信度 low。

## 最小修复设计

1. 新 attempt 前增加独立 worker license/ApplicationService/network 探针并保存原始输出。
2. correction 返回后强制检查 output 存在、UTF-8、hash、size、mtime_ns、step/tick/identity 和 transaction；缺失或非零返回立即 fail-closed。
3. 保留 stdout/stderr 与完整 command/cwd/PID；未知错误不得自动归类为网络。
4. 不修改 ANCF 核心、物理参数、数值门槛或错误码语义；不在同一 runtime 重试。

## 测试与边界

- Stage 67 专项：4 passed，0 failure，0 error。
- 故障注入：24/24 通过，覆盖 worker 探针缺失、网络/授权、return code、artifact、identity、非有限值、超时和 stale output，均 fail-closed。
- compileall：通过。
- 根目录：910 collected，909 passed，0 failure，0 error，1 skipped，258.823 s；日志已保存，测试本体终态为 OK。

当前 E5-B 不接受；E5-C 不启动。正式 Strouhal、stable VIV、lock-in、五/九 slice、长时 VIV和实验验证均未完成。只有在完成独立探针与 MATLAB correction 根因证据后，才可申请新的 E5-B attempt。
