# Stage 4D-C-A 严格 Restart 与分级延时报告

## 状态

本次没有执行选定配置严格 Restart，也没有执行 0.25–0.50–1.00 s 分级延时。原因是时间步子 Gate 先行失败：共同时间点 `qdot` 和 `qddot` NRMSE 分别为 `0.3908521876924054` 和 `1.0941190222479935`，因此协议禁止启动后续重型计算。

结果文件保留了明确的阻断状态：

- `results/07_stage4d_c_convergence/selected_config_restart.json`：`not_run_blocked_by_time_step_gate`
- `results/07_stage4d_c_convergence/staged_duration_summary.json`：`not_run_blocked_by_time_step_gate`

这两个文件不是通过或失败的虚构运行结果；它们只记录了停止条件、目标配置和未执行原因。

## 周期覆盖只读审计

ANCF 既有核心模型的 nElem=4 线性化频率读取为 `27.50934575579332 Hz`，对应第一结构周期 `0.03635128253784099 s`，1 s 约覆盖 `27.50934575579332` 个结构周期。developed-flow bank 频率为：Re80 `0.10733640842189707 Hz`、Re100 `0.14149994022481596 Hz`、Re120 `0.17832790498556134 Hz`；1 s 分别只有 `0.10733640842189707`、`0.14149994022481596`、`0.17832790498556134` 个脱涡周期。因此即使后续完成 1 s 工程延时，它也不足以形成 VIV 统计窗口，`insufficient_for_viv_statistics=true`。

## 五切片边界

`results/07_stage4d_c_convergence/five_slice_flow_bank_requirements.json` 仅为规划文件，明确要求为每个独立 Re 建立充分发展流场；本任务没有运行、复制、最近邻或插值伪造五切片 CFD。

## 结论边界

本报告只记录停止后的工程状态和周期覆盖边界，不宣布 Stage 4D-C-A Gate 通过，不宣布长期 VIV、锁定区、稳态振幅、主频收敛或疲劳结论。
