# Stage 4E-B1-v2 回归收口

- B1 专项：24/24（复用既有 B1 证据，未重跑 OpenFOAM）。
- 生命周期专项：11/11。
- Runtime hygiene：4/4。
- 调度器失败测试：3/3。
- 非 MATLAB 全项目回归：359/359。
- MATLAB 真实 persistent ANCF：`environment_blocked`（4 个误收集用例均初始化超时，owned 进程已清理）。
- 完整回归：未宣布通过；因 MATLAB 环境阻断停止。
- 任务 owned 进程：126 启动登记，126 关闭，残留 0。
- C 盘项目工件创建：0；runtime 活动进程：0。
- B1 既有证据：只读 hash 复核，未修改。

结论：B1 CFD 子门建议通过；B1 项目 Gate 建议不通过，待 MATLAB 环境恢复后再执行真实 persistent ANCF 和完整回归。
