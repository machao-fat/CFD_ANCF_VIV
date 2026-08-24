# Stage 19 完整短窗失败报告

`STAGE4F_C_FULL_SHORT_WINDOW_V1_GATE: do_not_pass`

Branch A 使用同一父 checkpoint、dt=0.0025 s 完成 20/20 步，时间 1.5075--1.5575 s，逐步冻结数值门槛均通过。A 生成 20 个 schema `0.2.1+stabilizer.1` unified checkpoint。

Branch B 从同一父 checkpoint 启动，前 5 步目标为 1.5200 s，但仅完成 step 0、step 1；step 2（1.515 s）在 MATLAB `correct_00000002` 阶段发生超时：`MATLAB correct_00000002 timed out`。该失败发生在结构 correct 阶段，尚无对应新 checkpoint；已精确关闭 owned processes 并保留 partial fields、日志、checkpoint 和 registry。B restart 15 步和 C dt/2 40 步均未启动。

观察到的 B 前两步 CFL、raw/applied force、速度、虚功、力转换和几何指标均在冻结门槛内；但 B 不完整，因此不能宣称 B restart identity 或 A/B 比较通过。该终态是环境/MATLAB 执行超时，不是 CFD 数值门槛失败。

相关前置 compileall、Stage 19 1/1、Stage 18 4/4、Stage 17 8/8、timestamp 7/7 通过；根目录 842/842 的最近已接受回归仍为通过，但本次生产源码变更后的完整根回归未在失败后重跑。父 checkpoint、父保护集和旧证据 hash 未变。

下一授权点：仅可调查 MATLAB correct timeout 的环境/进程证据，在全新 Stage 19 attempt 中重新执行 A/B；不得复用 B partial fields，不得进入 C，不得进入五/九切片或长时 VIV。
