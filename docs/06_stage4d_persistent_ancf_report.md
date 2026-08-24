# Stage 4D-A 持久 ANCF runner 报告

状态：`passed`（仅限持久 runner、等价性、连续性和逻辑 restart 子范围）。这不是 Stage 4D 总体通过，也不是长时间 VIV 验证。

## 身份与实现

- 协议：`0.2.1`
- 冻结三切片 manifest：`d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`
- MATLAB worker：`src/coupling/persistent_ancf_matlab/persistent_ancf_worker.m`
- Python client：`src/coupling/persistent_ancf/runner.py`
- ANCF 核心仍调用既有 `vertical_ttr_case`、`ancf_initialize`、`ancf_advance_step`、`ancf_slice_motion` 和 checkpoint state；没有复制内力、切线刚度或 Newmark 实现。

支持命令：`initialize`、`predict`、`correct`、`get_state`、`prepare_checkpoint`、`finalize_commit`、`discard_staged`、`load_checkpoint`、`heartbeat`、`shutdown`，另有兼容性的 `save_checkpoint`。

`predict` 从 committed 状态产生 prediction，不覆盖 committed；`correct` 从同一个 committed 状态产生 correction；`finalize_commit` 只在 native checkpoint 已准备后提交；`discard_staged` 清理两个 staged 状态；响应直接包含 `q/qdot/qddot`、时间、Newton 审计、局部张力范围、PID、command/operation 身份。超时、worker 退出、旧响应、重复 command 和 NaN/Inf 均 fail-closed。

## 定量结果

结果文件：`results/06_persistent_ancf_tests/persistent_equivalence_summary.json`、`persistent_1000_step_summary.json`、`persistent_restart_summary.json`。

- 20 步 batch/persistent：`q=0`、`qdot=0`、`qddot=0` 相对误差；切片运动最大相对误差 `2.0294667437592467e-16`。
- batch 总耗时 `214.9653461 s`，persistent 总耗时 `5.1863883 s`，平均步耗时分别为 `10.748267305 s` 和 `0.259319415 s`，加速比 `41.4479853`。
- 1000 步：单 MATLAB 进程启动次数 `1`，最终 `global_step=999`、`time=2.499999999999958 s`，所有状态有限，无 pending 状态。
- 1000 步命令数 `4002`；RSS 约 `9.17 MB -> 9.08 MB`，句柄数保持 `138`。
- 同一 worker 内 50+50 restart：checkpoint step 49、恢复时间 `0.125 s`，`q/qdot/qddot/time` 最大误差均为 `0`，worker 启动次数 `1`。

## 限制

batch 等价性严格匹配 Stage 4C-B 旧 batch wrapper 的默认物理模型；本阶段改变的是进程/通信生命周期，不改变物理参数。真实三切片中等步数尚未执行，因为 developed-flow 前置准入未通过。
