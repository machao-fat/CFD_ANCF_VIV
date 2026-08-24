# Stage 4D-A-v2 子 Gate review

## 身份

- schema：`0.2.1`
- frozen manifest：`d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`
- 旧 `results/06_developed_flow` 和旧 `cases/openfoam/stage4d_developed_flow` 未修改。

## ProcessLimiter

v2 烟测先完成三套 case 的全部 prepare/checkMesh/setFields，再连续提交三个真实 pimpleFoam 进程。`max_processes=2`，第三个提交等待实际 permit；没有使用 sleep 或伪造时间区间。

- 三个进程返回码：`0,0,0`
- 三个日志：均出现 `End`
- `peak_active_count=2`
- 独立时间区间 `interval_peak_active_count=2`
- `permit_leak=false`
- 实际 PID、slice_id、start/end ns、exit_code、condition 已写入 `results/06_developed_flow_v2/process_limiter_real_overlap_v2.json`。

该证据只覆盖 ProcessLimiter 子 Gate，不接入正式100步耦合 campaign。

## Developed-flow 子 Gate

Re=100 和 Re=120 已满足：至少12个完整周期、两个相邻窗口各至少3周期、连续三个评估点、Cd变化≤3%、Cl fluctuation RMS变化≤5%、频率变化≤3%、峰峰值变化≤5%、包络变化≤2%、FFT/零交叉差异≤3%、St范围和CFL条件。

Re=80 在240 s仍不满足 Cl RMS 和峰峰值窗口条件，因此整体 bank 仍为 `blocked`。候选入口文件：

`results/06_stage4d_medium_run/stage4d_a_v2_entry_candidate.json`

该文件的 `status` 仅为 `blocked`，并给出 `建议不进入` 与 `建议不通过`。

## 入口边界

本轮没有启动：

- 100步真实三切片 CFD–ANCF；
- 真实三切片3+5 restart；
- 长时间自由VIV；
- 锁定区参数扫描；
- 曲线立管、强耦合或机器学习代理。

只有 Sol 主Agent复核 v2 bank 后，才可决定是否调整 Re=80 的物理/数值策略；本结果不授权下一阶段耦合。

