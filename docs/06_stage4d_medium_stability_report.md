# Stage 4D-A 中等步数稳定性报告

状态：`blocked / not_executed`。

任务 D 的启动条件要求 A、B、C 全部通过。持久 ANCF 子 Gate 和 ProcessLimiter 子 Gate 已通过，但 Re=80/100/120 的 developed-flow 两窗口稳定判据均在 60 s 上限未通过。因此没有启动 100 步真实三切片 CFD–ANCF，也没有生成任何伪造的 100 步、10 步 restart、能量或 checkpoint 通过证据。

## 已执行的进程证据

`results/06_stage4d_medium_run/process_concurrency_audit.json` 是三个独立 fresh OpenFOAM one-step smoke 的真实进程审计：`max_processes=2`，三个进程均返回 0 并含 `End`，permit 无泄漏，按真实 start/end 区间计算峰值并发为 `1`。该 smoke 明确标注为“不含 ANCF 耦合”，只证明 limiter 的真实子进程生命周期，不能替代三切片结构时间屏障。

## 未执行对象

以下文件均明确写入 `not_executed`，原因是 developed-flow 前置准入被阻塞：

- `stage4d_100step_summary.json`
- `stage4d_restart_comparison.json`
- `stage4d_energy_audit.json`
- `checkpoint_hash_audit.json`

因此本报告没有 W_CFD、W_structure、ΔW_c 或 E_c 数值，也没有声明 100 步 CFL、运动增量、力、ANCF Newton 或统一 checkpoint 通过。`stage4d_a_candidate_summary.json` 给出 `建议不进入`、`建议不通过`。

## 后续接口请求

需要 Sol 主Agent 决定是否调整 developed-flow 稳定策略、初始扰动/网格或将 C 阻塞证据交回协议讨论；本子任务不自行修改正式 dt、manifest、physics hash，也不自行启用 Aitken 或长时间 VIV。
