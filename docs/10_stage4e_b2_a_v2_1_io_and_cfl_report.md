# Stage 4E-B2-A-v2.1：I/O、暖机与在线 CFL 修复报告

## 范围

本轮只针对最大 Re、medium 网格的 laminar 和 kOmegaSST 做暖机、固定时间步生产和模型筛查。未运行 coarse/fine 长算、dt/2、expanded domain、low/middle、九切片或 ANCF。

正式 fresh run：`20260815T145000000Z_stage4e_b2_a_v2_1_medium_screening`。

## I/O 修复

- 正式 `controlDict` 不含逐步 `yPlus` function object。
- force/forceCoeffs 每 5 个 solver 步写出，采样间隔 0.002 s；按 `f_max=3.8203427648377293 Hz` 计算为 130.8783 samples/cycle。
- 完整场每 1000 步写出，即 0.4 s；正式 10.5 s 预计约 28 个时间目录，并保留 continuation block 终点场。
- SST 的 yPlus 只在暖机结束和每个 block 结束以 `pimpleFoam -postProcess -func yPlus -latestTime` 调用；laminar 明确记为不适用，不作为模型准入指标。

## I/O 等价与性能

1000 步 medium laminar 对照中，old stepwise-yPlus 与 new sparse-output 的 raw force、forceCoeffs、U、p 最大相对误差均为 0，等价测试通过。

最终 production case 实际各有 28 个数值时间目录；laminar case 约 20.667 MB，kOmegaSST case 约 29.104 MB。force history 仍按 0.002 s 采样，场输出与力输出相互独立。

旧方案 1001 个时间目录、6.273 MB、17 s clock；新方案 2 个时间目录、1.956 MB、7 s clock，时间目录减少 99.8002%，steps/s 从 124.69 提升到 134.07。磁盘减少 68.8244%，未达到建议的 80% 门槛。主要原因是两个方案共享约 1.16 MB 的 constant 基线，无法通过继续稀疏时间目录把该固定成本消除；因此本轮不以“性能改善不足”冒充通过。

## 暖机与 CFL

暖机使用 `adjustTimeStep yes`、`maxCo=0.5`、`maxDeltaT=0.0004 s`，至约 0.2 s；生产从 `latestTime` 开始，`adjustTimeStep no`、固定 `dt=0.0004 s`。生产统计排除暖机。

在线监视器增量解析日志中的 `Courant Number`，在 `CFL >= 0.8` 或 NaN/Inf 时停止登记的 PID 及精确子树。制造日志测试覆盖 0.49、0.799、0.8、1.2、NaN/Inf 和不完整行，专项通过。

laminar 生产最大 CFL 为 0.4624675993248588；kOmegaSST 为 0.4545301513663924，均低于 0.5 目标和 0.8 硬停止。两模型均返回码 0、日志含 `End`，未触发在线停止。

## 结论

时间目录门槛通过，磁盘缩减建议门槛未通过；该项与尚未进行的网格、时间步和域收敛一起阻止下一阶段准入。完整数值证据见 fresh run 结果目录。
